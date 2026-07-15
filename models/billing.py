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
    source     = db.Column(db.String(80), default="")    # qayerdan keldi (CRM)
    tags       = db.Column(db.String(200), default="")   # vergul bilan (VIP, korporativ…)
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    # Shaxsiy portal — maxfiy havola tokeni (parolsiz kirish; havola = kalit)
    portal_token = db.Column(db.String(48), default="", index=True)
    # Telegram bog'lanish (bot /start <token> orqali)
    tg_chat_id   = db.Column(db.String(24), default="")
    created_by = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def hours_purchased(self):
        # FAQAT to'langan paketlar balans beradi (bonus paketlar is_paid=True).
        # To'lov "kutilmoqda"ga qaytsa yoki o'chsa — soat ham qaytadi (arvoh
        # balans oldini olish: pul kirmagan bo'lsa soat berilmaydi).
        from sqlalchemy import func
        return float(db.session.query(
            func.coalesce(func.sum(Payment.hours), 0)).filter(
            Payment.teacher_id == self.id,
            Payment.kind == "package",
            Payment.is_paid.is_(True)).scalar() or 0)

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

    # ── CRM metrikalari (bitta mijoz uchun; ro'yxatда batch ishlatiladi) ──
    def ltv(self):
        """Umumiy to'lagan puli (LTV) — tasdiqlangan to'lovlar yig'indisi."""
        from sqlalchemy import func
        return float(db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.teacher_id == self.id,
            Payment.is_paid.is_(True)).scalar() or 0)

    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

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
            "source": self.source or "", "tags": self.tag_list(),
            "balance_hours": self.balance_hours(),
        }


# CRM segment kodlari va ular haqida ma'lumot (UI'да ranglar/yorliqlar)
CRM_SEGMENTS = {
    "new":      ("🆕 Yangi", "blue"),
    "active":   ("🟢 Faol", "green"),
    "cooling":  ("🟡 Sovumoqda", "amber"),
    "sleeping": ("🟠 Uxlagan", "amber"),
    "lost":     ("🔴 Yo'qotilgan", "red"),
}


class ClientNote(db.Model):
    """CRM o'zaro aloqa tarixi — eslatma, qo'ng'iroq, uchrashuv, follow-up.

    Bitta `note` matn maydonidan farqli: sanali, muallifli, turli xil
    yozuvlar oqimi. Follow-up turi due_date + done bilan «vazifa» bo'ladi.
    """
    __tablename__ = "client_notes"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                           nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    author = db.Column(db.String(120), default="")
    kind = db.Column(db.String(16), default="note")   # note|call|meeting|followup
    text = db.Column(db.String(1000), default="")
    due_date = db.Column(db.String(10), default="")   # follow-up: YYYY-MM-DD
    done = db.Column(db.Boolean, default=False)        # follow-up bajarildi

    def to_dict(self):
        return {"id": self.id, "teacher_id": self.teacher_id,
                "at": self.at.strftime("%Y-%m-%d %H:%M") if self.at else "",
                "author": self.author or "", "kind": self.kind,
                "text": self.text or "", "due_date": self.due_date or "",
                "done": self.done}


NOTE_KINDS = {"note": "📝 Eslatma", "call": "📞 Qo'ng'iroq",
              "meeting": "🤝 Uchrashuv", "followup": "⏰ Follow-up"}


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
    # Qaysi hisob (moliya hamyoni)ga tushgan — to'lash paytida tanlanadi
    wallet     = db.Column(db.String(60), default="")
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
            "method": self.method or "", "wallet": self.wallet or "",
            "date": self.date,
            "is_paid": self.is_paid, "note": self.note or "",
        }


def package_balances():
    """Barcha mijozlar paket balansi — BITTA aggregat + BITTA yuklama so'rovда.

    Teacher.balance_hours() har mijoz uchun 2-3 aggregat so'rov yuboradi;
    dashboard/attention uni har faol mijozда aylantirib chaqirgani uchun N+1
    hosil bo'lardi (60 mijoz ≈ 360+ so'rov). Bu funksiya o'rniga:
      • sotib olingan soat — bitta GROUP BY sum (faqat to'langan paketlar);
      • ishlatilgan soat — paket bronlarini (active/done/noshow) bir marta
        yuklab, Python'да yig'amiz (Booking.hours — hisoblanadigan property,
        SQL'да sum qilib bo'lmaydi).
    Natija: {teacher_id: {"purchased": x, "used": y, "balance": z}}.
    """
    from sqlalchemy import func
    from models.studio import Booking
    purchased = {}
    for tid, hrs in db.session.query(
            Payment.teacher_id,
            func.coalesce(func.sum(Payment.hours), 0)).filter(
            Payment.kind == "package",
            Payment.is_paid.is_(True)).group_by(Payment.teacher_id).all():
        purchased[tid] = float(hrs or 0)
    used = {}
    for b in Booking.query.filter(
            Booking.pay_type == "package",
            Booking.status.in_(("active", "done", "noshow"))).all():
        used[b.teacher_id] = used.get(b.teacher_id, 0.0) + b.hours
    out = {}
    for tid in set(purchased) | set(used):
        p = purchased.get(tid, 0.0)
        u = used.get(tid, 0.0)
        out[tid] = {"purchased": p, "used": u, "balance": round(p - u, 2)}
    return out
