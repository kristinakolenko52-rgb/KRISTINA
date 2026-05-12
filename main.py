import os
import secrets
import string
import stripe
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Cookie, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from models import SessionLocal, engine, Base, User, Booking, BlockedSlot, Settings, FAQItem
from auth import hash_password, verify_password, create_token, decode_token
from telegram_notify import send_new_booking, send_status_change
import email_notify

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PK = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WH = os.getenv("STRIPE_WEBHOOK_SECRET", "")
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000")

app = FastAPI(title="Kristina MUA")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _gen_code() -> str:
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def _migrate():
    conn = engine.raw_connection()
    cur = conn.cursor()
    for sql in [
        "ALTER TABLE users ADD COLUMN referral_code TEXT",
        "ALTER TABLE users ADD COLUMN referred_by TEXT",
        "ALTER TABLE users ADD COLUMN pending_discount INTEGER DEFAULT 0",
        "ALTER TABLE bookings ADD COLUMN photo_permission INTEGER DEFAULT 0",
        "ALTER TABLE bookings ADD COLUMN discount_applied INTEGER DEFAULT 0",
        "ALTER TABLE bookings ADD COLUMN discount_reason TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN reminder_sent INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN admin_notes TEXT DEFAULT ''",
    ]:
        try:
            cur.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()
    db = SessionLocal()
    for u in db.query(User).filter(User.referral_code == None).all():
        u.referral_code = _gen_code()
    db.commit()
    db.close()


def _credit_referrer(booking: Booking, db):
    if not booking.user_id:
        return
    user = db.query(User).filter(User.id == booking.user_id).first()
    if not user or not user.referred_by:
        return
    referrer = db.query(User).filter(User.referral_code == user.referred_by).first()
    if referrer:
        referrer.pending_discount = 5
        email_notify.send_referral_credit(referrer.email, referrer.name)


# ── Bootstrap admin ─────────────────────────────────────────────────────────
def _bootstrap():
    db = SessionLocal()
    admin_email = os.getenv("ADMIN_EMAIL", "admin@kristina.cz")
    existing = db.query(User).filter(User.email == admin_email).first()
    if not existing:
        db.add(User(
            name="Admin",
            email=admin_email,
            password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "admin1234")),
            is_admin=True,
            referral_code=_gen_code(),
        ))
        db.commit()
    elif not existing.referral_code:
        existing.referral_code = _gen_code()
        db.commit()
    db.close()


def _get_settings(db) -> dict:
    return {r.key: r.value for r in db.query(Settings).all()}


def _set_setting(db, key: str, value: str):
    s = db.query(Settings).filter(Settings.key == key).first()
    if s:
        s.value = value
    else:
        db.add(Settings(key=key, value=value))
    db.commit()


def _bootstrap_settings():
    db = SessionLocal()
    cfg = _get_settings(db)
    defaults = {"work_start": "10", "work_end": "20", "work_days": "0,1,2,3,4"}
    for k, v in defaults.items():
        if k not in cfg:
            db.add(Settings(key=k, value=v))
    db.commit()
    db.close()


_FAQ_DEFAULTS = [
    ("Как записаться на макияж?", "Вы можете записаться через форму на странице <a href='/booking' style='color:#C9969D;'>Запись</a>. Выберите услугу, удобную дату и время, укажите контактные данные — и всё готово.", "Запись и оплата", 1),
    ("Нужен ли предоплата?", "При онлайн-записи доступна оплата картой через защищённую систему Stripe. Оплата подтверждает бронирование. Если вы записываетесь лично или по телефону — оплата производится в день услуги.", "Запись и оплата", 2),
    ("Можно ли отменить или перенести запись?", "Да. Отмену или перенос необходимо сделать <strong>не позднее чем за 24 часа</strong> до записи. Отменить запись можно в личном кабинете или написав мне напрямую. При отмене менее чем за 24 часа депозит не возвращается.", "Запись и оплата", 3),
    ("Какие способы оплаты принимаете?", "Принимаю оплату картой (Visa, Mastercard) онлайн через Stripe, а также наличными (CZK) и банковским переводом.", "Запись и оплата", 4),
    ("Сколько времени занимает макияж?", "<strong>Дневной/нюдовый макияж</strong> — около 60 минут.<br/><strong>Вечерний макияж</strong> — 60–90 минут.<br/><strong>Свадебный макияж</strong> — 90–120 минут.<br/><strong>Урок макияжа</strong> — 90–120 минут.", "Услуги", 1),
    ("Нужно ли делать пробный макияж перед свадьбой?", "Настоятельно рекомендую! Пробный макияж позволяет вместе выработать идеальный образ, подобрать нужные оттенки и убедиться, что вы будете чувствовать себя уверенно в самый важный день. Пробный макияж включён в стоимость свадебного пакета.", "Услуги", 2),
    ("Какой косметикой вы работаете?", "Работаю исключительно с профессиональной косметикой: <strong>Charlotte Tilbury</strong>, <strong>MAC</strong>, <strong>NARS</strong>, <strong>Armani Beauty</strong>, <strong>Huda Beauty</strong>. Вся косметика проверена на гипоаллергенность.", "Услуги", 3),
    ("Приедете ли вы ко мне домой?", "Да! Выезд на дом или в отель возможен в пределах Праги и Пражского района. Стоимость выезда: <strong>+300 CZK</strong>. При бронировании выберите опцию «Выезд на дом» и укажите адрес.", "Услуги", 4),
    ("Как мне подготовиться к макияжу?", "— Очистите кожу лица и нанесите привычный уходовый крем за 30 минут до визита.<br/>— Не наносите тональное средство или тушь заранее.<br/>— Если носите линзы — лучше надеть их после макияжа.<br/>— Возьмите примеры образов, которые вам нравятся.", "Подготовка", 1),
    ("Что делать, если у меня чувствительная кожа или аллергия?", "Пожалуйста, сообщите об этом при записи в поле «Пожелания». Я учту особенности вашей кожи и при необходимости проведу тест на аллергическую реакцию заранее.", "Подготовка", 2),
    ("Делаете ли вы макияж мужчинам или детям?", "Специализируюсь на макияже для женщин. Для сценического и корректирующего макияжа для мужчин — пожалуйста, уточните заранее.", "Подготовка", 3),
]


def _bootstrap_faq():
    db = SessionLocal()
    if db.query(FAQItem).count() == 0:
        for q, a, cat, num in _FAQ_DEFAULTS:
            db.add(FAQItem(question=q, answer=a, category=cat, order_num=num))
        db.commit()
    db.close()


Base.metadata.create_all(bind=engine)
_migrate()
_bootstrap()
_bootstrap_settings()
_bootstrap_faq()


# ── Reminder scheduler ───────────────────────────────────────────────────────
def _reminder_job():
    now = datetime.now()
    lo = now + timedelta(minutes=50)
    hi = now + timedelta(minutes=70)
    db = SessionLocal()
    try:
        bookings = db.query(Booking).filter(
            Booking.status == "confirmed",
            Booking.reminder_sent == False,
        ).all()
        for b in bookings:
            try:
                bdt = datetime.strptime(f"{b.date} {b.time}", "%Y-%m-%d %H:%M")
                if lo <= bdt <= hi:
                    email_notify.send_reminder(b.email, b.first_name, b.service_label, b.date, b.time)
                    b.reminder_sent = True
            except Exception:
                pass
        db.commit()
    finally:
        db.close()


_scheduler = BackgroundScheduler()
_scheduler.add_job(_reminder_job, 'interval', minutes=5, id='reminder')
_scheduler.start()


# ── Auth helpers ─────────────────────────────────────────────────────────────
def _get_user(token: Optional[str] = Cookie(None)) -> Optional[User]:
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    db = SessionLocal()
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    db.close()
    return user


def _require_user(token: Optional[str] = Cookie(None)) -> User:
    user = _get_user(token)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


def _require_admin(token: Optional[str] = Cookie(None)) -> User:
    user = _get_user(token)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


# ── Page routes ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "index.html", {"user": _get_user(token)})

@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "portfolio.html", {"user": _get_user(token)})

@app.get("/prices", response_class=HTMLResponse)
async def prices(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "prices.html", {"user": _get_user(token)})

@app.get("/booking", response_class=HTMLResponse)
async def booking(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "booking.html", {"user": _get_user(token), "stripe_pk": STRIPE_PK})

@app.get("/before-after", response_class=HTMLResponse)
async def before_after(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "before_after.html", {"user": _get_user(token)})

@app.get("/faq", response_class=HTMLResponse)
async def faq(request: Request, token: Optional[str] = Cookie(None)):
    db = SessionLocal()
    items = db.query(FAQItem).filter(FAQItem.is_visible == True).order_by(FAQItem.category, FAQItem.order_num).all()
    db.close()
    categories: dict = {}
    for item in items:
        categories.setdefault(item.category, []).append(item)
    return templates.TemplateResponse(request, "faq.html", {"user": _get_user(token), "categories": categories})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, token: Optional[str] = Cookie(None)):
    if _get_user(token):
        return RedirectResponse("/cabinet")
    return templates.TemplateResponse(request, "login.html", {"user": None})

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/")
    resp.delete_cookie("token")
    return resp

@app.get("/cabinet", response_class=HTMLResponse)
async def cabinet(request: Request, token: Optional[str] = Cookie(None)):
    user = _get_user(token)
    if not user:
        return RedirectResponse("/login")
    db = SessionLocal()
    bookings = db.query(Booking).filter(Booking.user_id == user.id).order_by(Booking.created_at.desc()).all()
    db.close()
    return templates.TemplateResponse(request, "cabinet.html", {"user": user, "bookings": bookings})

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, token: Optional[str] = Cookie(None)):
    user = _get_user(token)
    if not user or not user.is_admin:
        return RedirectResponse("/login")
    db = SessionLocal()
    bookings = db.query(Booking).order_by(Booking.created_at.desc()).all()
    users = db.query(User).order_by(User.created_at.desc()).all()
    blocked = db.query(BlockedSlot).order_by(BlockedSlot.date, BlockedSlot.time).all()
    stats = {
        "total": len(bookings),
        "pending": sum(1 for b in bookings if b.status == "pending"),
        "confirmed": sum(1 for b in bookings if b.status == "confirmed"),
        "cancelled": sum(1 for b in bookings if b.status == "cancelled"),
        "revenue": sum(b.total for b in bookings if b.payment_status == "paid"),
        "users": len(users),
    }
    faq_items = db.query(FAQItem).order_by(FAQItem.category, FAQItem.order_num).all()
    cfg = _get_settings(db)
    db.close()
    return templates.TemplateResponse(request, "admin.html", {
        "user": user, "bookings": bookings, "users": users, "blocked": blocked,
        "stats": stats, "faq_items": faq_items, "settings": cfg,
    })

@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request, booking_id: Optional[int] = None, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "payment_success.html", {"user": _get_user(token), "booking_id": booking_id})

@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(request: Request, token: Optional[str] = Cookie(None)):
    return RedirectResponse("/booking")

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request, token: Optional[str] = Cookie(None)):
    return templates.TemplateResponse(request, "privacy.html", {"user": _get_user(token)})


# ── Auth API ──────────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    password: str
    referral_code: Optional[str] = ""

class LoginIn(BaseModel):
    email: str
    password: str

@app.post("/api/register")
async def api_register(data: RegisterIn):
    db = SessionLocal()
    if db.query(User).filter(User.email == data.email).first():
        db.close()
        return JSONResponse({"ok": False, "error": "email_exists"}, status_code=400)
    referred_by = data.referral_code.upper().strip() if data.referral_code else None
    if referred_by and not db.query(User).filter(User.referral_code == referred_by).first():
        referred_by = None  # ignore invalid codes
    user = User(
        name=data.name, email=data.email, phone=data.phone,
        password_hash=hash_password(data.password),
        referral_code=_gen_code(),
        referred_by=referred_by,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    token = create_token(user.id, user.is_admin)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("token", token, max_age=60*60*24*14, httponly=True, samesite="lax")
    return resp

@app.post("/api/login")
async def api_login(data: LoginIn):
    db = SessionLocal()
    user = db.query(User).filter(User.email == data.email).first()
    db.close()
    if not user or not verify_password(data.password, user.password_hash):
        return JSONResponse({"ok": False, "error": "invalid_credentials"}, status_code=401)
    token = create_token(user.id, user.is_admin)
    resp = JSONResponse({"ok": True, "is_admin": user.is_admin})
    resp.set_cookie("token", token, max_age=60*60*24*14, httponly=True, samesite="lax")
    return resp


# ── Booking API ───────────────────────────────────────────────────────────────
class BookingIn(BaseModel):
    service: str
    service_label: str
    location: str
    date: str
    time: str
    first_name: str
    last_name: str
    phone: str
    email: str
    address: Optional[str] = ""
    wishes: Optional[str] = ""
    total: int
    photo_permission: bool = False

@app.post("/api/booking")
async def api_create_booking(data: BookingIn, token: Optional[str] = Cookie(None)):
    db = SessionLocal()

    # Check slot not already taken
    existing = db.query(Booking).filter(
        Booking.date == data.date,
        Booking.time == data.time,
        Booking.status != "cancelled"
    ).first()
    if existing:
        db.close()
        return JSONResponse({"ok": False, "error": "slot_taken"}, status_code=409)

    # Check not blocked
    blocked = db.query(BlockedSlot).filter(
        BlockedSlot.date == data.date,
        BlockedSlot.time == data.time
    ).first()
    if blocked:
        db.close()
        return JSONResponse({"ok": False, "error": "slot_blocked"}, status_code=409)

    user = _get_user(token)

    # Calculate discounts
    discount = 0
    reasons = []
    if data.photo_permission:
        discount += round(data.total * 0.05)
        reasons.append("photo")
    if user and (user.pending_discount or 0) > 0:
        discount += round(data.total * user.pending_discount / 100)
        reasons.append("referral")

    final_total = max(data.total - discount, 0)

    booking = Booking(
        user_id=user.id if user else None,
        service=data.service,
        service_label=data.service_label,
        location=data.location,
        date=data.date,
        time=data.time,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        email=data.email,
        address=data.address,
        wishes=data.wishes,
        total=final_total,
        photo_permission=data.photo_permission,
        discount_applied=discount,
        discount_reason="+".join(reasons),
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    booking_id = booking.id

    # Reset used referral discount
    if user and (user.pending_discount or 0) > 0 and "referral" in reasons:
        db.query(User).filter(User.id == user.id).update({"pending_discount": 0})
        db.commit()

    db.close()

    # Telegram notification
    await send_new_booking(data.model_dump())

    # Stripe checkout if configured
    if stripe.api_key:
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "czk",
                        "product_data": {"name": data.service_label},
                        "unit_amount": data.total * 100,
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=f"{SITE_URL}/payment/success?booking_id={booking_id}",
                cancel_url=f"{SITE_URL}/payment/cancel",
                metadata={"booking_id": str(booking_id)},
            )
            db2 = SessionLocal()
            db2.query(Booking).filter(Booking.id == booking_id).update(
                {"stripe_session_id": session.id}
            )
            db2.commit()
            db2.close()
            return {"ok": True, "booking_id": booking_id, "stripe_url": session.url}
        except Exception:
            pass

    # No Stripe — auto-confirm
    db3 = SessionLocal()
    db3.query(Booking).filter(Booking.id == booking_id).update({"status": "confirmed"})
    db3.commit()
    db3.close()
    return {"ok": True, "booking_id": booking_id, "stripe_url": None}


@app.post("/api/payment/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WH)
    except Exception:
        raise HTTPException(status_code=400)
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        booking_id = int(session["metadata"].get("booking_id", 0))
        if booking_id:
            db = SessionLocal()
            b = db.query(Booking).filter(Booking.id == booking_id).first()
            if b:
                b.status = "confirmed"
                b.payment_status = "paid"
                _credit_referrer(b, db)
            db.commit()
            db.close()
    return {"ok": True}


@app.get("/api/work-settings")
async def get_work_settings():
    db = SessionLocal()
    cfg = _get_settings(db)
    db.close()
    work_days = [int(d) for d in cfg.get("work_days", "0,1,2,3,4").split(",") if d.strip()]
    return {
        "work_start": int(cfg.get("work_start", "10")),
        "work_end": int(cfg.get("work_end", "20")),
        "work_days": work_days,
    }


@app.get("/api/available-slots/{date}")
async def available_slots(date: str):
    db = SessionLocal()
    cfg = _get_settings(db)
    work_start = int(cfg.get("work_start", "10"))
    work_end = int(cfg.get("work_end", "20"))
    work_days = [int(d) for d in cfg.get("work_days", "0,1,2,3,4").split(",") if d.strip()]
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        if dt.weekday() not in work_days:
            db.close()
            return {"available": []}
    except ValueError:
        db.close()
        return {"available": []}
    all_times = [f"{h:02d}:00" for h in range(work_start, work_end + 1)]
    taken = {b.time for b in db.query(Booking).filter(
        Booking.date == date, Booking.status != "cancelled"
    ).all()}
    blocked = {s.time for s in db.query(BlockedSlot).filter(BlockedSlot.date == date).all()}
    db.close()
    return {"available": [t for t in all_times if t not in taken and t not in blocked]}


@app.post("/api/booking/{booking_id}/cancel")
async def cancel_booking(booking_id: int, token: Optional[str] = Cookie(None)):
    user = _get_user(token)
    if not user:
        raise HTTPException(status_code=401)
    db = SessionLocal()
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        db.close()
        raise HTTPException(status_code=404)
    if not user.is_admin and b.user_id != user.id:
        db.close()
        raise HTTPException(status_code=403)
    b.status = "cancelled"
    db.commit()
    db.close()
    return {"ok": True}


# ── Admin API ─────────────────────────────────────────────────────────────────
class StatusUpdate(BaseModel):
    status: str

@app.patch("/api/admin/booking/{booking_id}/status")
async def admin_update_status(booking_id: int, data: StatusUpdate, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        db.close()
        raise HTTPException(status_code=404)
    b.status = data.status
    client_name = f"{b.first_name} {b.last_name}"
    if data.status == "confirmed":
        _credit_referrer(b, db)
    db.commit()
    db.close()
    await send_status_change(booking_id, data.status, client_name)
    return {"ok": True}


class BlockSlotIn(BaseModel):
    date: str
    time: str
    reason: Optional[str] = ""

@app.post("/api/admin/block-slot")
async def admin_block_slot(data: BlockSlotIn, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    db.add(BlockedSlot(date=data.date, time=data.time, reason=data.reason))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/admin/block-slot/{slot_id}")
async def admin_unblock_slot(slot_id: int, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    s = db.query(BlockedSlot).filter(BlockedSlot.id == slot_id).first()
    if s:
        db.delete(s)
        db.commit()
    db.close()
    return {"ok": True}

@app.get("/api/admin/bookings")
async def admin_list_bookings(token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    bookings = db.query(Booking).order_by(Booking.created_at.desc()).all()
    db.close()
    return [{"id": b.id, "service_label": b.service_label, "date": b.date, "time": b.time,
             "first_name": b.first_name, "last_name": b.last_name, "phone": b.phone,
             "email": b.email, "total": b.total, "status": b.status,
             "payment_status": b.payment_status, "location": b.location,
             "created_at": b.created_at.isoformat()} for b in bookings]


# ── Admin Settings API ────────────────────────────────────────────────────────
class SettingsIn(BaseModel):
    work_start: int
    work_end: int
    work_days: list

@app.get("/api/admin/settings")
async def admin_get_settings(token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    cfg = _get_settings(db)
    db.close()
    return cfg

@app.post("/api/admin/settings")
async def admin_save_settings(data: SettingsIn, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    _set_setting(db, "work_start", str(data.work_start))
    _set_setting(db, "work_end", str(data.work_end))
    _set_setting(db, "work_days", ",".join(str(d) for d in sorted(data.work_days)))
    db.close()
    return {"ok": True}


# ── Admin FAQ API ─────────────────────────────────────────────────────────────
class FAQIn(BaseModel):
    question: str
    answer: str
    category: str = "Общие вопросы"
    order_num: int = 0
    is_visible: bool = True

@app.get("/api/admin/faq")
async def admin_get_faq(token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    items = db.query(FAQItem).order_by(FAQItem.category, FAQItem.order_num).all()
    result = [{"id": i.id, "question": i.question, "answer": i.answer,
               "category": i.category, "order_num": i.order_num, "is_visible": i.is_visible}
              for i in items]
    db.close()
    return result

@app.post("/api/admin/faq")
async def admin_add_faq(data: FAQIn, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    item = FAQItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    result = {"id": item.id, "question": item.question, "answer": item.answer,
              "category": item.category, "order_num": item.order_num, "is_visible": item.is_visible}
    db.close()
    return result

@app.put("/api/admin/faq/{item_id}")
async def admin_update_faq(item_id: int, data: FAQIn, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    item = db.query(FAQItem).filter(FAQItem.id == item_id).first()
    if not item:
        db.close()
        raise HTTPException(status_code=404)
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/admin/faq/{item_id}")
async def admin_delete_faq(item_id: int, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    item = db.query(FAQItem).filter(FAQItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"ok": True}


# ── Admin Client Card API ─────────────────────────────────────────────────────
@app.get("/api/admin/client/{user_id}")
async def admin_get_client(user_id: int, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        db.close()
        raise HTTPException(status_code=404)
    bookings = db.query(Booking).filter(Booking.user_id == user_id).order_by(Booking.created_at.desc()).all()
    result = {
        "id": user.id, "name": user.name, "email": user.email,
        "phone": user.phone or "", "referral_code": user.referral_code or "",
        "referred_by": user.referred_by or "", "pending_discount": user.pending_discount or 0,
        "admin_notes": getattr(user, "admin_notes", "") or "",
        "created_at": user.created_at.strftime("%d.%m.%Y"),
        "bookings": [{"id": b.id, "service_label": b.service_label, "date": b.date,
                      "time": b.time, "total": b.total, "status": b.status,
                      "payment_status": b.payment_status, "discount_applied": b.discount_applied}
                     for b in bookings],
    }
    db.close()
    return result

class NotesIn(BaseModel):
    notes: str

@app.post("/api/admin/client/{user_id}/notes")
async def admin_save_notes(user_id: int, data: NotesIn, token: Optional[str] = Cookie(None)):
    _require_admin(token)
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        db.close()
        raise HTTPException(status_code=404)
    user.admin_notes = data.notes
    db.commit()
    db.close()
    return {"ok": True}
