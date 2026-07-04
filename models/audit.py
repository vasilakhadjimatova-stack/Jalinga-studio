"""Audit-log — kim, qachon, nima qilgani (moliya/jamoa muhim amallari).

Professional talab: pul va foydalanuvchi o'zgarishlarida «kim qildi» izi
bo'lishi shart. Faqat rahbar ko'radi. Yengil: bitta jadval + `record()`.
"""
from datetime import datetime

from database import db


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_name = db.Column(db.String(120), default="")   # kim (snapshot — o'chsa ham qoladi)
    user_id = db.Column(db.Integer, index=True)
    action = db.Column(db.String(40), index=True)        # create|update|delete|pay|repay|toggle
    entity = db.Column(db.String(40), index=True)        # transaction|debt|wallet|category|payment|user
    summary = db.Column(db.String(400), default="")      # inson o'qiy oladigan tavsif
    ip = db.Column(db.String(48), default="")


def record(action, entity, summary=""):
    """Joriy foydalanuvchi amalini yozadi. Commit chaqiruvchida (yoki keyingi
    db.session.commit bilan birga). Xato bo'lsa jim — asosiy amal to'xtamaydi."""
    try:
        from flask import request, has_request_context
        from core.auth import current_user
        u = current_user()
        ip = ""
        if has_request_context():
            ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or request.remote_addr or "")
        db.session.add(AuditLog(
            user_name=(u.name if u else "—"), user_id=(u.id if u else None),
            action=action[:40], entity=entity[:40], summary=str(summary)[:400],
            ip=ip[:48]))
    except Exception:  # audit hech qachon asosiy oqimni buzmasin
        pass
