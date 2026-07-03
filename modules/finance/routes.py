"""Moliya — to'lovlar jurnali + kutilayotganlarni tasdiqlash."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func

from core.auth import login_required, admin_required
from core.timeutils import current_month_iso
from database import db
from models.billing import Teacher, Payment

bp = Blueprint("finance", __name__)


def _safe_back(month=None):
    """Ochiq-yo'naltirishдан himoya: faqat ichki /finance sahifasiga."""
    return redirect(url_for("finance.index", month=month))


@bp.route("/finance")
@login_required
def index():
    month = (request.args.get("month") or current_month_iso()).strip()[:7]
    rows = Payment.query.filter(Payment.date.like(month + "%")).order_by(
        Payment.is_paid.asc(), Payment.id.desc()).all()
    tmap = {t.id: t.name for t in Teacher.query.all()}
    items = []
    for p in rows:
        d = p.to_dict()
        d["teacher_name"] = tmap.get(p.teacher_id, "?")
        items.append(d)
    paid = sum(p.amount or 0 for p in rows if p.is_paid)
    pending = sum(p.amount or 0 for p in rows if not p.is_paid)
    return render_template("finance.html", items=items, month=month,
                           paid=paid, pending=pending)


@bp.route("/finance/<int:pid>/toggle", methods=["POST"])
@admin_required
def toggle(pid):
    p = Payment.query.get_or_404(pid)
    p.is_paid = not p.is_paid
    db.session.commit()
    flash("✅ To'landi deb belgilandi" if p.is_paid else "↩️ Kutilmoqda holatiga qaytarildi",
          "success")
    return _safe_back(p.date[:7] if p.date else None)


@bp.route("/finance/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    p = Payment.query.get_or_404(pid)
    month = p.date[:7] if p.date else None
    db.session.delete(p)
    db.session.commit()
    flash("🗑 To'lov o'chirildi", "success")
    return _safe_back(month)
