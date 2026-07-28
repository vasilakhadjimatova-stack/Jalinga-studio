import secrets
from datetime import datetime

from database import db

ROLES = ["admin", "operator", "montaj", "buxgalter"]

# Rol yorliqlari — butun tizim uchun yagona manba (jamoa, vazifalar, TG)
ROLE_LABELS = {
    "admin": "Rahbar",
    "operator": "Operator",
    "montaj": "Montajchi",
    "buxgalter": "Buxgalter",
}


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
    def is_boss(self):
        """Rahbarmi? — vazifa taxtasida butun jamoani ko'radi va istalgan
        xodimga vazifa tayinlay oladi. Studiyada rahbar = admin."""
        return self.role == "admin"

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @staticmethod
    def staff(active_only=True):
        """Vazifa biriktirish uchun tanlanadigan xodimlar (ism bo'yicha)."""
        q = User.query
        if active_only:
            q = q.filter(User.is_active.is_(True))
        return q.order_by(User.role.asc(), User.name.asc()).all()

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
