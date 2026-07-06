import secrets
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
    # Telegram bog'lanish — ALOHIDA uzun maxfiy token orqali (login kodi EMAS,
    # aks holda bot /start bilan login kodini brute-force qilish mumkin edi).
    tg_chat_id = db.Column(db.String(24), default="")
    tg_token   = db.Column(db.String(48), default="", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def ensure_tg_token(self):
        """Telegram ulash uchun uzun tasodifiy token (yo'q bo'lsa yaratadi)."""
        if not self.tg_token:
            self.tg_token = secrets.token_urlsafe(18)   # ~24 belgi
        return self.tg_token

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
