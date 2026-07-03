"""Montaj oqimi (post-production) — har yozuv uchun ish kartasi.

Oqim: recorded (yozildi) → editing (montajда) → review (tekshiruvda)
      → delivered (topshirildi ✅)
Yozuv "done" bo'lganda karta avto-yaraladi. SLA — default 3 kun.
"""
from datetime import datetime, timedelta

from database import db

EDIT_STATUSES = ["recorded", "editing", "review", "delivered"]
EDIT_LABELS = {
    "recorded":  ("🎬 Yozildi", "blue"),
    "editing":   ("✂️ Montajda", "amber"),
    "review":    ("👀 Tekshiruvda", "amber"),
    "delivered": ("✅ Topshirildi", "green"),
}
SLA_DAYS = 3


class EditJob(db.Model):
    __tablename__ = "edit_jobs"
    id           = db.Column(db.Integer, primary_key=True)
    booking_id   = db.Column(db.Integer, unique=True, nullable=True, index=True)
    teacher_id   = db.Column(db.Integer, nullable=False, index=True)
    title        = db.Column(db.String(200), nullable=False)
    status       = db.Column(db.String(12), nullable=False, default="recorded",
                             index=True)
    assignee_id  = db.Column(db.Integer, nullable=True, index=True)  # montajchi
    due_date     = db.Column(db.String(10), default="")   # YYYY-MM-DD (SLA)
    link         = db.Column(db.String(400), default="")  # tayyor video havolasi
    note         = db.Column(db.String(300), default="")
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow,
                             onupdate=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def for_booking(b, teacher_name=""):
        """Yozuv tugagach karta yaratadi (bor bo'lsa o'shani qaytaradi)."""
        job = EditJob.query.filter_by(booking_id=b.id).first()
        if job:
            return job
        due = (datetime.utcnow() + timedelta(days=SLA_DAYS)).strftime("%Y-%m-%d")
        job = EditJob(booking_id=b.id, teacher_id=b.teacher_id,
                      title=f"{teacher_name or 'Dars'} — {b.date} {b.start}",
                      due_date=due)
        db.session.add(job)
        return job

    def is_overdue(self):
        if self.status == "delivered" or not self.due_date:
            return False
        from core.timeutils import today_iso
        return self.due_date < today_iso()

    def to_dict(self):
        lbl, color = EDIT_LABELS.get(self.status, (self.status, "gray"))
        return {
            "id": self.id, "booking_id": self.booking_id,
            "teacher_id": self.teacher_id, "title": self.title,
            "status": self.status, "status_label": lbl, "status_color": color,
            "assignee_id": self.assignee_id, "due_date": self.due_date or "",
            "link": self.link or "", "note": self.note or "",
            "overdue": self.is_overdue(),
        }
