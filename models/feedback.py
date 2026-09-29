"""Mijoz fikri — yozuvdan keyin baholash (CSAT + NPS).

Impulse ERP'dagi «tadbirdan keyin so'rovnoma» g'oyasi studiyaga
moslashtirilgan: yozuv «Yozildi ✓» bo'lgach mijozga maxfiy havola ketadi
(Telegram ulangan bo'lsa botga, bo'lmasa kabinetda ko'rinadi), mijoz
login'siz 1 daqiqada baholaydi.

Past baho — «xizmatni tiklash» (service recovery): rahbarga shoshilinch
vazifa tushadi, mijoz norozi holda ketib qolmaydi.
"""
import json
import secrets
from datetime import datetime

from database import db

# (kalit, sarlavha, emoji, savol) — sahifa va panel shu YAGONA ro'yxatdan
RATING_QUESTIONS = [
    ("overall",  "Umumiy taassurot",       "🌟", "Yozuv umuman qanday o'tdi?"),
    ("tech",     "Ovoz, yorug'lik, texnika", "🎙️", "Jihozlar sifati va ishlashi qanday edi?"),
    ("operator", "Operator yordami",       "🎬", "Operator e'tiborli va professional bo'ldimi?"),
    ("comfort",  "Qulaylik va tozalik",    "🛋️", "Studiya toza, qulay va o'z vaqtida tayyor edimi?"),
    ("value",    "Narx-sifat",             "💰", "To'lagan narxingizga arzidimi?"),
]
RATING_KEYS = [k for k, _, _, _ in RATING_QUESTIONS]
RATING_LABELS = {k: lbl for k, lbl, _, _ in RATING_QUESTIONS}
LOW_THRESHOLD = 3      # shundan PAST (1–2) baho — «nima kamchilik?» so'raladi


class Survey(db.Model):
    __tablename__ = "surveys"
    id          = db.Column(db.Integer, primary_key=True)
    booking_id  = db.Column(db.Integer, db.ForeignKey("bookings.id"),
                            unique=True, index=True, nullable=False)
    teacher_id  = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                            index=True, nullable=False)
    token       = db.Column(db.String(48), unique=True, index=True,
                            nullable=False)
    status      = db.Column(db.String(12), nullable=False, default="pending")
    # pending (yuborilgan, baholanmagan) / done (mijoz baholadi)

    overall     = db.Column(db.Integer)       # 1–5
    tech        = db.Column(db.Integer)
    operator    = db.Column(db.Integer)
    comfort     = db.Column(db.Integer)
    value       = db.Column(db.Integer)
    recommend   = db.Column(db.Integer)       # NPS 0–10
    comment     = db.Column(db.Text, default="")
    issues      = db.Column(db.Text, default="")   # JSON {kalit: kamchilik}

    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    sent_at     = db.Column(db.String(16), default="")   # Telegram'ga ketgan
    done_at     = db.Column(db.String(16), default="")   # mijoz baholagan

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(24)[:48]

    @property
    def ratings(self):
        return [getattr(self, k) for k in RATING_KEYS if getattr(self, k)]

    @property
    def avg_rating(self):
        r = self.ratings
        return round(sum(r) / len(r), 1) if r else None

    @property
    def issues_dict(self):
        try:
            return json.loads(self.issues) if self.issues else {}
        except (ValueError, TypeError):
            return {}

    def set_issues(self, d):
        self.issues = json.dumps(d, ensure_ascii=False) if d else ""

    @property
    def is_unhappy(self):
        """Norozi mijoz: umumiy ≤3, biror o'lcham ≤2 yoki NPS ≤6."""
        if self.status != "done":
            return False
        if self.overall is not None and self.overall <= 3:
            return True
        if any(v <= 2 for v in self.ratings):
            return True
        return self.recommend is not None and self.recommend <= 6
