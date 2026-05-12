import os
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def send_new_booking(b: dict):
    if not BOT_TOKEN or not CHAT_ID:
        return
    loc = "🏠 Выезд на дом" if b.get("location") == "home" else "🏛 Салон"
    text = (
        f"🌸 <b>Новая запись!</b>\n\n"
        f"👤 {b['first_name']} {b['last_name']}\n"
        f"📞 {b['phone']}\n"
        f"✉️ {b['email']}\n"
        f"💄 {b['service_label']}\n"
        f"{loc}\n"
        f"📅 {b['date']} в {b['time']}\n"
        f"💰 <b>{b['total']} CZK</b>"
    )
    if b.get("address"):
        text += f"\n🏠 {b['address']}"
    if b.get("wishes"):
        text += f"\n💬 {b['wishes'][:120]}"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
    except Exception:
        pass


async def send_status_change(booking_id: int, new_status: str, client_name: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    icons = {"confirmed": "✅", "cancelled": "❌", "pending": "⏳"}
    icon = icons.get(new_status, "ℹ️")
    text = f"{icon} Запись #{booking_id} ({client_name}) → <b>{new_status}</b>"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
    except Exception:
        pass
