"""Ustoz (mijoz) + to'lovlar/paket balansi + shaxsiy portal.

Balans mantiqi (shaffof, yagona formula):
  sotib olingan soatlar (Payment kind='package')
  − ishlatilgan soatlar (Booking pay_type='package', status active/done)
Soatbay bronlar balansga tegmaydi — ularga alohida Payment yoziladi.
"""
from datetime import datetime

from database import db

PAY_KINDS = {"hourly": "Soatbay", "package": "Paket (soat)"}
PAY_METHODS = ["naqd", "karta", "o'tkazma", "click/payme"]


class Teacher(db.Model):
    __tablename__ = "teachers"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    phone      = db.Column(db.String(50), default="")
    telegram   = db.Column(db.String(64), default="")
    subject    = db.Column(db.String(120), default="")   # fan/yo'nalish
    note       = db.Column(db.Text, default="")
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    # Shaxsiy portal — maxfiy havola tokeni (parolsiz kirish; havola = kalit)
    portal_token = db.Column(db.String(48), default="", index=True)
    # Telegram bog'lanish (bot /start <token> orqali)
    tg_chat_id   = db.Column(db.String(24), default="")
    created_by = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def hours_purchased(self):
        from sqlalchemy import func
        return float(db.session.query(
            func.coalesce(func.sum(Payment.hours), 0)).filter(
            Payment.teacher_id == self.id,
            Payment.kind == "package").scalar() or 0)

    def hours_used(self):
        """Ishlatilgan soatlar. "noshow" (kelmadi) HAM kuyadi — 24 soat
        qoidasining mantiqiy davomi: vaqtida bekor qilmagan mijoz slotni
        band qilib turdi. Faqat "cancelled" soatni qaytaradi."""
        from models.studio import Booking
        rows = Booking.query.filter(
            Booking.teacher_id == self.id,
            Booking.pay_type == "package",
            Booking.status.in_(("active", "done", "noshow"))).all()
        return sum(b.hours for b in rows)

    def balance_hours(self):
        return round(self.hours_purchased() - self.hours_used(), 2)

    def ensure_token(self):
        """Portal tokeni yo'q bo'lsa yaratadi (commit chaqiruvchida)."""
        if not (self.portal_token or "").strip():
            import secrets
            self.portal_token = secrets.token_urlsafe(24)[:48]
        return self.portal_token

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "phone": self.phone or "",
            "telegram": self.telegram or "", "subject": self.subject or "",
            "note": self.note or "", "is_active": self.is_active,
            "balance_hours": self.balance_hours(),
        }


class Payment(db.Model):
    __tablename__ = "jalinga_payments"
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                           nullable=False, index=True)
    booking_id = db.Column(db.Integer, nullable=True)     # soatbay bron uchun
    kind       = db.Column(db.String(10), nullable=False, default="hourly")
    amount     = db.Column(db.Float, nullable=False, default=0)   # so'm
    hours      = db.Column(db.Float, nullable=False, default=0)   # paket: soat
    method     = db.Column(db.String(20), default="naqd")
    date       = db.Column(db.String(10), nullable=False, index=True)
    is_paid    = db.Column(db.Boolean, nullable=False, default=True, index=True)
    note       = db.Column(db.String(300), default="")
    created_by = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "teacher_id": self.teacher_id,
            "booking_id": self.booking_id, "kind": self.kind,
            "kind_label": PAY_KINDS.get(self.kind, self.kind),
            "amount": self.amount or 0, "hours": self.hours or 0,
            "method": self.method or "", "date": self.date,
            "is_paid": self.is_paid, "note": self.note or "",
        }
