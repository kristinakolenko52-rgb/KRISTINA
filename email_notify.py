import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("EMAIL_SMTP_USER", "")
SMTP_PASS = os.getenv("EMAIL_SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "") or SMTP_USER


def _send(msg: EmailMessage):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        return
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
    except Exception:
        pass


def send_reminder(to_email: str, first_name: str, service_label: str, date: str, time: str):
    msg = EmailMessage()
    msg["Subject"] = f"Напоминание о записи — сегодня в {time} | KRISTINA"
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        f"Здравствуйте, {first_name}!\n\n"
        f"Напоминаем, что через час у вас запись:\n"
        f"💄 {service_label}\n"
        f"📅 {date} в {time}\n\n"
        f"Если нужно перенести или отменить — свяжитесь со мной заранее.\n\n"
        f"До встречи!\n"
        f"KRISTINA · Визажист · Прага"
    )
    _send(msg)


def send_referral_credit(to_email: str, first_name: str):
    msg = EmailMessage()
    msg["Subject"] = "🎁 Вам начислена скидка 5% | KRISTINA"
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        f"Здравствуйте, {first_name}!\n\n"
        f"Ваш приглашённый друг прошёл процедуру — спасибо, что рекомендуете меня!\n\n"
        f"🎁 Вам начислена скидка 5% на следующую запись.\n"
        f"Она применится автоматически при оформлении.\n\n"
        f"KRISTINA · Визажист · Прага"
    )
    _send(msg)
