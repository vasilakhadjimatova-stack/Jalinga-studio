"""Kirish — 6 xonali shaxsiy kod (Impulse uslubi: parolsiz, tez).

Rollar: admin (hammasi) / operator (bron+ustoz) — keyin kengayadi.
CSRF: sessiya tokeni; har POST forma `_csrf` maydonini yuboradi
(base.html JS avtomatik qo'shadi).
"""
import secrets
from functools import wraps

from flask import session, redirect, url_for, request, flash, abort

from models.user import User


def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None


def login_by_code(code):
    code = (code or "").strip()
    if not code:
        return None, "Kod kiritilmadi"
    u = User.query.filter_by(code=code, is_active=True).first()
    if not u:
        return None, "Kod noto'g'ri"
    session["user_id"] = u.id
    session.permanent = True
    return u, None


def logout_user():
    session.pop("user_id", None)


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    """POST so'rovlarda _csrf (forma) yoki X-CSRF-Token (header) shart."""
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
    if not sent or sent != session.get("_csrf"):
        abort(400, "CSRF token xato")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("auth.login", next=request.path))
        if request.method == "POST":
            check_csrf()
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("auth.login", next=request.path))
        if not u.is_admin:
            flash("Bu amal faqat rahbar uchun", "error")
            return redirect(url_for("dashboard.index"))
        if request.method == "POST":
            check_csrf()
        return f(*args, **kwargs)
    return wrapper
