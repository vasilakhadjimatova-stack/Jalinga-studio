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


# ── Vaqtga bog'liq chegirmalar (narx qoidalari) — bo'sh soatlarni to'ldirish ──
@bp.route("/pricing")
@admin_required
def pricing():
    from models.pricing import PriceRule
    rules = PriceRule.query.order_by(
        PriceRule.is_active.desc(), PriceRule.start_hour.asc()).all()
    studios = Studio.query.order_by(Studio.sort.asc()).all()
    smap = {s.id: s.name for s in studios}
    return render_template("pricing.html",
                           rules=[r.to_dict() | {"days_label": r.days_label(),
                                  "studio_name": smap.get(r.studio_id, "Barcha studiya")}
                                  for r in rules],
                           studios=[s.to_dict() for s in studios])


@bp.route("/pricing/save", methods=["POST"])
@admin_required
def pricing_save():
    from models.pricing import PriceRule
    f = request.form
    rid = (f.get("id") or "").strip()
    r = PriceRule.query.get(int(rid)) if rid.isdigit() else None
    if not r:
        r = PriceRule()
        db.session.add(r)
    r.name = (f.get("name") or "Chegirma").strip()[:80] or "Chegirma"
    try:
        r.studio_id = int(f.get("studio_id") or 0) or None
    except (ValueError, TypeError):
        r.studio_id = None
    # Hafta kunlari (checkbox'lar): 0..6
    days = [d for d in f.getlist("days") if d.isdigit() and 0 <= int(d) <= 6]
    r.days = ",".join(days)
    try:
        r.start_hour = max(0, min(23, int(f.get("start_hour") or 9)))
        r.end_hour = max(1, min(24, int(f.get("end_hour") or 14)))
    except (ValueError, TypeError):
        r.start_hour, r.end_hour = 9, 14
    if r.end_hour <= r.start_hour:
        flash("⛔ Tugash soati boshlanishdan katta bo'lsin", "error")
        return redirect(url_for("studios.pricing"))
    try:
        r.discount = max(0, min(90, int(f.get("discount") or 0)))
    except (ValueError, TypeError):
        r.discount = 0
    r.is_active = bool(f.get("is_active"))
    db.session.commit()
    flash(f"✅ «{r.name}» — {r.discount}% chegirma saqlandi", "success")
    return redirect(url_for("studios.pricing"))


@bp.route("/pricing/delete", methods=["POST"])
@admin_required
def pricing_delete():
    from models.pricing import PriceRule
    rid = (request.form.get("id") or "").strip()
    r = PriceRule.query.get(int(rid)) if rid.isdigit() else None
    if r:
        db.session.delete(r)
        db.session.commit()
        flash("🗑 Qoida o'chirildi", "success")
    return redirect(url_for("studios.pricing"))
