"""Studiya va bron — Jalinga yadrosi.

Bron = studiya + ustoz + sana + vaqt oralig'i. Bir studiyada bir vaqtda
faqat bitta yozuv (overlap tekshiruvi hall_conflict'ning soddalashgani).
"""
from datetime import datetime

from database import db

BOOKING_STATUSES = {
    "active":    ("Rejalashtirilgan", "blue"),
    "done":      ("Yozildi ✓", "green"),
    "cancelled": ("Bekor qilindi", "gray"),
    "noshow":    ("Kelmadi", "red"),
}


def _to_minutes(hhmm):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


class Studio(db.Model):
    __tablename__ = "studios"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    hourly_rate = db.Column(db.Float, nullable=False, default=0)   # so'm/soat
    color       = db.Column(db.String(10), default="#6098F2")
    is_active   = db.Column(db.Boolean, nullable=False, default=True)
    sort        = db.Column(db.Integer, default=100)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name,
                "description": self.description or "",
                "hourly_rate": self.hourly_rate or 0, "color": self.color,
                "is_active": self.is_active, "sort": self.sort or 100}


class Booking(db.Model):
    __tablename__ = "bookings"
    id           = db.Column(db.Integer, primary_key=True)
    studio_id    = db.Column(db.Integer, db.ForeignKey("studios.id"),
                             nullable=False, index=True)
    teacher_id   = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                             nullable=False, index=True)
    date         = db.Column(db.String(10), nullable=False, index=True)  # YYYY-MM-DD
    start        = db.Column(db.String(5), nullable=False, default="10:00")
    end          = db.Column(db.String(5), nullable=False, default="12:00")
    status       = db.Column(db.String(12), nullable=False, default="active",
                             index=True)
    pay_type     = db.Column(db.String(10), nullable=False, default="hourly")
    # hourly (soatbay to'lov) / package (paket balansidan yechiladi)
    operator     = db.Column(db.String(120), default="")   # kim yozib beradi
    note         = db.Column(db.String(300), default="")
    created_by   = db.Column(db.String(120), default="")
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def hours(self):
        """Davomiylik (soat, kasr bilan): 10:00–11:30 → 1.5."""
        return max(0, (_to_minutes(self.end) - _to_minutes(self.start)) / 60)

    def status_label(self):
        return BOOKING_STATUSES.get(self.status, (self.status, "gray"))[0]

    def status_color(self):
        return BOOKING_STATUSES.get(self.status, (self.status, "gray"))[1]

    @staticmethod
    def conflict(studio_id, date, start, end, exclude_id=None):
        """Shu studiya+sanada vaqt ustma-ust tushadigan FAOL bron bormi."""
        s, e = _to_minutes(start), _to_minutes(end)
        if e <= s:
            return None
        q = Booking.query.filter(
            Booking.studio_id == studio_id, Booking.date == date,
            Booking.status.in_(("active", "done")))
        if exclude_id:
            q = q.filter(Booking.id != exclude_id)
        for b in q.all():
            if _to_minutes(b.start) < e and _to_minutes(b.end) > s:
                return b
        return None

    def to_dict(self):
        return {
            "id": self.id, "studio_id": self.studio_id,
            "teacher_id": self.teacher_id, "date": self.date,
            "start": self.start, "end": self.end, "hours": self.hours,
            "status": self.status, "status_label": self.status_label(),
            "status_color": self.status_color(), "pay_type": self.pay_type,
            "operator": self.operator or "", "note": self.note or "",
        }
