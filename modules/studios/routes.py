"""Studiyalar — CRUD (faqat rahbar tahrirlaydi)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, admin_required, current_user
from database import db
from models.studio import Studio

bp = Blueprint("studios", __name__)


@bp.route("/studios")
@login_required
def index():
    rows = Studio.query.order_by(Studio.sort.asc(), Studio.id.asc()).all()
    return render_template("studios.html", studios=[s.to_dict() for s in rows])


@bp.route("/studios/save", methods=["POST"])
@admin_required
def save():
    f = request.form
    sid = f.get("id", "").strip()
    s = Studio.query.get(int(sid)) if sid.isdigit() else None
    if not s:
        s = Studio()
        db.session.add(s)
    s.name = (f.get("name") or "").strip()[:120] or "Studiya"
    s.description = (f.get("description") or "").strip()[:300]
    import math
    try:
        rate = float((f.get("hourly_rate") or "0").replace(" ", "").replace(",", ""))
        s.hourly_rate = rate if (math.isfinite(rate)
                                 and 0 <= rate <= 1_000_000_000) else 0
    except (ValueError, TypeError):
        s.hourly_rate = 0
    s.color = (f.get("color") or "#6098F2").strip()[:10]
    s.is_active = bool(f.get("is_active"))
    try:
        s.sort = int(f.get("sort") or 100)
    except (ValueError, TypeError):
        s.sort = 100
    db.session.commit()
    flash(f"✅ «{s.name}» saqlandi", "success")
    return redirect(url_for("studios.index"))
