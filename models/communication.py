"""
KOMMUNIKATSIYA YADROSI — vazifalar tizimi (Impulse ERP'dan moslashtirilgan).

Jalinga studiyasida jamoa kichik va ROLLARGA bo'linadi (rahbar / operator /
montajchi / buxgalter). Shuning uchun Impulse'ning «bo'limlararo» vazifa
mantig'i bu yerda «rolerlararo» ko'rinishда ishlaydi:

  1. Notification — aniq odamga yoki butun rolega signal (inbox + Telegram)
  2. Task         — vazifa/so'rov uzatish, 4 bosqichli oqim (Kanban)
  3. TaskComment  — vazifa muhokamasi (chat)
  4. TaskActivity — o'zgarishlar tarixi (audit trail)
  5. TaskWatcher  — kuzatuvchilar (mas'uldan tashqari xabar oladiganlar)

Faollik oqimi AuditLog'ga yoziladi (core.comms.log_event) — alohida Event
jadvali kerak emas.
"""
from datetime import datetime, timedelta

from database import db


class Notification(db.Model):
    """Aniq foydalanuvchiga yoki butun rolega yo'naltirilgan signal.
    user_id berilsa — shaxsiy; aks holda role bo'yicha hammaga."""
    __tablename__ = "notifications"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    role        = db.Column(db.String(20), nullable=True, index=True)
    title       = db.Column(db.String(200), nullable=False)
    body        = db.Column(db.Text, nullable=False, default="")
    level       = db.Column(db.String(20), nullable=False, default="info")  # info/warning/urgent
    link        = db.Column(db.String(300), nullable=False, default="")
    is_read     = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "level": self.level,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else "",
            "ago": _time_ago(self.created_at),
        }


class Task(db.Model):
    """Vazifa/so'rov uzatish.
    assigner (kim topshirdi) → assignee (kim bajaradi) yoki butun role.
    Status kuzatiladi: new → accepted → in_progress → done (+ cancelled)."""
    __tablename__ = "tasks"

    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, nullable=False, default="")

    assigner_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigner_name = db.Column(db.String(120), nullable=False, default="Tizim")
    assignee_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    assignee_name = db.Column(db.String(120), nullable=False, default="")
    # Qo'shimcha mas'ullar — vergul bilan ajratilgan ID lar: "12,15,18"
    co_assignee_ids   = db.Column(db.Text, default="")
    co_assignee_names = db.Column(db.String(500), default="")
    # Rolega topshirilsa (aniq xodim emas): admin/operator/montaj/buxgalter
    target_role   = db.Column(db.String(20), nullable=True, index=True)

    status        = db.Column(db.String(20), nullable=False, default="new", index=True)
    priority      = db.Column(db.String(20), nullable=False, default="normal")
    # low / normal / high / urgent

    related_type  = db.Column(db.String(50), nullable=False, default="")  # booking/teacher...
    related_id    = db.Column(db.Integer, nullable=True)
    is_auto       = db.Column(db.Boolean, nullable=False, default=False)

    progress      = db.Column(db.Integer, nullable=False, default=0)  # 0-100%

    due_date      = db.Column(db.String(10), nullable=False, default="")   # YYYY-MM-DD
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    accepted_at   = db.Column(db.DateTime, nullable=True)
    started_at    = db.Column(db.DateTime, nullable=True)
    completed_at  = db.Column(db.DateTime, nullable=True)

    STATUS_LABELS = {
        "new": "Yangi",
        "accepted": "Qabul qildim",
        "in_progress": "Jarayonda",
        "done": "Tugallandi",
        "cancelled": "Bekor qilindi",
    }
    STATUS_FLOW = {
        "new": "accepted",
        "accepted": "in_progress",
        "in_progress": "done",
    }
    STATUS_ACTIONS = {
        "new": "✓ Qabul qildim",
        "accepted": "▶ Ishni boshladim",
        "in_progress": "✓ Bajardim",
    }
    PRIORITY_LABELS = {
        "low": "Past",
        "normal": "O'rta",
        "high": "Yuqori",
        "urgent": "Shoshilinch",
    }

    def co_assignee_id_list(self):
        raw = (self.co_assignee_ids or "").strip()
        if not raw:
            return []
        try:
            return [int(x) for x in raw.split(",") if x.strip().isdigit()]
        except (ValueError, AttributeError):
            return []

    def all_assignee_ids(self):
        ids = []
        if self.assignee_id:
            ids.append(self.assignee_id)
        ids.extend(self.co_assignee_id_list())
        return list(dict.fromkeys(ids))

    def is_assignee(self, user_id):
        if not user_id:
            return False
        return user_id in self.all_assignee_ids()

    def role_label(self):
        from models.user import ROLE_LABELS
        return ROLE_LABELS.get(self.target_role, self.target_role or "")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "assigner_name": self.assigner_name,
            "assignee_name": self.assignee_name or (self.role_label() + " (jamoa)" if self.target_role else "—"),
            "co_assignee_ids": self.co_assignee_id_list(),
            "co_assignee_names": self.co_assignee_names or "",
            "all_assignee_count": len(self.all_assignee_ids()),
            "target_role": self.target_role,
            "target_role_label": self.role_label(),
            "status": self.status,
            "status_label": self.STATUS_LABELS.get(self.status, self.status),
            "next_action": self.STATUS_ACTIONS.get(self.status, ""),
            "next_status": self.STATUS_FLOW.get(self.status, ""),
            "priority": self.priority,
            "priority_label": self.PRIORITY_LABELS.get(self.priority, self.priority),
            "related_type": self.related_type,
            "related_id": self.related_id,
            "is_auto": self.is_auto,
            "progress": self.progress or 0,
            "due_date": self.due_date,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else "",
            "ago": _time_ago(self.created_at),
        }


class TaskComment(db.Model):
    """Vazifa muhokamasi — bajaruvchi va topshiruvchi gaplasha oladi."""
    __tablename__ = "task_comments"

    id          = db.Column(db.Integer, primary_key=True)
    task_id     = db.Column(db.Integer, db.ForeignKey("tasks.id"),
                            nullable=False, index=True)
    user_id     = db.Column(db.Integer, nullable=True)
    user_name   = db.Column(db.String(120), default="")
    user_role   = db.Column(db.String(20), default="")
    body        = db.Column(db.Text, nullable=False)
    is_system   = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        # created_at UTC saqlanadi — ko'rsatishda Toshkent (+5) vaqti
        _tk = (self.created_at + timedelta(hours=5)) if self.created_at else None
        return {
            "id": self.id, "task_id": self.task_id,
            "user_id": self.user_id, "user_name": self.user_name,
            "user_role": self.user_role, "body": self.body,
            "is_system": self.is_system,
            "created_at": _tk.strftime("%d.%m.%Y %H:%M") if _tk else "",
            "ago": _time_ago(self.created_at),
        }


class TaskActivity(db.Model):
    """Vazifa tarixchi — har bir o'zgarish (status, priority, assignee, deadline)."""
    __tablename__ = "task_activities"

    id          = db.Column(db.Integer, primary_key=True)
    task_id     = db.Column(db.Integer, db.ForeignKey("tasks.id"),
                            nullable=False, index=True)
    user_id     = db.Column(db.Integer, nullable=True)
    user_name   = db.Column(db.String(120), default="Tizim")
    kind        = db.Column(db.String(20), nullable=False)
    old_value   = db.Column(db.String(200), default="")
    new_value   = db.Column(db.String(200), default="")
    note        = db.Column(db.String(300), default="")
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "task_id": self.task_id,
            "user_name": self.user_name, "kind": self.kind,
            "old_value": self.old_value, "new_value": self.new_value,
            "note": self.note,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else "",
            "ago": _time_ago(self.created_at),
        }


class TaskWatcher(db.Model):
    """Vazifani kuzatuvchilar (assignee dan tashqari) — yangiliklar oladi."""
    __tablename__ = "task_watchers"

    id          = db.Column(db.Integer, primary_key=True)
    task_id     = db.Column(db.Integer, db.ForeignKey("tasks.id"),
                            nullable=False, index=True)
    user_id     = db.Column(db.Integer, nullable=False, index=True)
    user_name   = db.Column(db.String(120), default="")
    added_at    = db.Column(db.DateTime, default=datetime.utcnow)


# ── Yordamchi: "qancha vaqt oldin" ────────────────────────────────
def _time_ago(dt):
    if not dt:
        return ""
    delta = datetime.utcnow() - dt
    s = int(delta.total_seconds())
    if s < 60:
        return "hozirgina"
    if s < 3600:
        return f"{s // 60} daqiqa oldin"
    if s < 86400:
        return f"{s // 3600} soat oldin"
    if s < 604800:
        return f"{s // 86400} kun oldin"
    return dt.strftime("%d.%m.%Y")
