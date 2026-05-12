from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./kristina.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    phone = Column(String, default="")
    password_hash = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    referral_code = Column(String, nullable=True)
    referred_by = Column(String, nullable=True)
    pending_discount = Column(Integer, default=0)


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    service = Column(String)
    service_label = Column(String)
    location = Column(String)
    date = Column(String)
    time = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    phone = Column(String)
    email = Column(String)
    address = Column(String, default="")
    wishes = Column(Text, default="")
    total = Column(Integer)
    status = Column(String, default="pending")        # pending | confirmed | cancelled
    payment_status = Column(String, default="unpaid") # unpaid | paid
    stripe_session_id = Column(String, default="")
    photo_permission = Column(Boolean, default=False)
    discount_applied = Column(Integer, default=0)
    discount_reason = Column(String, default="")
    reminder_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class BlockedSlot(Base):
    __tablename__ = "blocked_slots"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)
    time = Column(String)
    reason = Column(String, default="")


class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(Text, default="")


class FAQItem(Base):
    __tablename__ = "faq_items"
    id = Column(Integer, primary_key=True)
    question = Column(String)
    answer = Column(Text)
    category = Column(String, default="Общие вопросы")
    order_num = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
