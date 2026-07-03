"""Jamoa boshqaruvi — xodimlar (admin/operator/montajchi) faqat rahbar uchun.

Himoyalar: kod unikal va kamida 4 belgi; o'zini faolsizlantirib bo'lmaydi;
OXIRGI faol admin faolsizlantirilmaydi/rolini pasaytirib bo'lmaydi.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import admin_required, current_user
from database import db
from models.user import User, ROLES

bp = Blueprint("team", __name__)

ROLE_LABELS = {"admin": "👑 Rahbar", "operator": "🎥 Operator",
               "montaj": "✂️ Montajchi"}


def _last_active_admin(u):
    """u — tizimdagi yagona faol adminmi."""
    return (u.role == "admin" and User.query.filter_by(
        role="admin", is_active=True).filter(User.id != u.id).count() == 0)


@bp.route("/team")
@admin_required
def index():
    rows = User.query.order_by(User.is_active.desc(), User.role.asc(),
                               User.name.asc()).all()
    return render_template("team.html", team=rows, roles=ROLES,
                           role_labels=ROLE_LABELS)


@bp.route("/team/save", methods=["POST"])
@admin_required
def save():
    me = current_user()
    f = request.form
    uid = (f.get("id") or "").strip()
    u = User.query.get(int(uid)) if uid.isdigit() else None
    is_new = u is None

    name = (f.get("name") or "").strip()[:120]
    code = (f.get("code") or "").strip()[:12]
    role = f.get("role") if f.get("role") in ROLES else "operator"
    active = bool(f.get("is_active"))

    if not name:
        flash("⛔ Ism kiritilishi shart", "error")
        return redirect(url_for("team.index"))
    if is_new or code:
        if len(code) < 4 or not code.isdigit():
            flash("⛔ Kod kamida 4 ta raqamdan iborat bo'lsin", "error")
            return redirect(url_for("team.index"))
        dup = User.query.filter_by(code=code).first()
        if dup and (is_new or dup.id != u.id):
            flash(f"⛔ Bu kod band ({dup.name}). Boshqa kod tanlang.", "error")
            return redirect(url_for("team.index"))

    if is_new:
        u = User(name=name, code=code, role=role, is_active=True)
        db.session.add(u)
        db.session.commit()
        flash(f"✅ {name} qo'shildi ({ROLE_LABELS.get(role, role)}). "
              f"Kirish kodi: {code}", "success")
        return redirect(url_for("team.index"))

    # ── Tahrirlash himoyalari ──
    if u.id == me.id and not active:
        flash("⛔ O'zingizni faolsizlantira olmaysiz", "error")
        return redirect(url_for("team.index"))
    if _last_active_admin(u) and (role != "admin" or not active):
        flash("⛔ Tizimda kamida bitta faol rahbar qolishi shart", "error")
        return redirect(url_for("team.index"))

    u.name = name
    if code:
        u.code = code
    u.role = role
    u.is_active = active
    db.session.commit()
    flash(f"✅ {u.name} yangilandi", "success")
    return redirect(url_for("team.index"))
