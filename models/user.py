from datetime import datetime

from database import db

ROLES = ["admin", "operator", "montaj", "buxgalter"]


class User(db.Model):
    __tablename__ = "users"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    code       = db.Column(db.String(12), unique=True, nullable=False, index=True)
    role       = db.Column(db.String(20), nullable=False, default="operator")
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    # Telegram bog'lanish (bot /start <kod> orqali) — rahbarga digest/eslatma
    tg_chat_id = db.Column(db.String(24), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_buxgalter(self):
        return self.role == "buxgalter"

    @property
    def can_finance(self):
        """Moliya bo'limiga kirish huquqi (rahbar yoki buxgalter)."""
        return self.role in ("admin", "buxgalter")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "role": self.role,
                "is_active": self.is_active}
