"""Boshliq paneli — biznes bir ekranda: bugun, bandlik, tushum, balanslar."""
from datetime import timedelta

from flask import Blueprint, render_template, redirect, url_for
from sqlalchemy import func

from core.auth import login_required, current_user
from core.timeutils import now_tashkent, today_iso, current_month_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    # Buxgalter uchun bosh sahifa — Moliya (studiya paneli kerak emas)
    u = current_user()
    if u and u.is_buxgalter:
        return redirect(url_for("finance.index"))
    today = today_iso()
    month = current_month_iso()

    todays = Booking.query.filter(
        Booking.date == today,
        Booking.status.in_(("active", "done"))).order_by(
        Booking.start.asc()).all()

    # Shu oy tushumi (to'langan to'lovlar)
    month_revenue = float(db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.date.like(month + "%"), Payment.is_paid.is_(True)
    ).scalar() or 0)
    month_pending = float(db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.date.like(month + "%"), Payment.is_paid.is_(False)
    ).scalar() or 0)

    # Haftalik bandlik %: yozilgan soatlar / (studiyalar × 12 soat × 7 kun)
    week_ago = (now_tashkent().date() - timedelta(days=6)).strftime("%Y-%m-%d")
    week_bookings = Booking.query.filter(
        Booking.date >= week_ago, Booking.date <= today,
        Booking.status.in_(("active", "done"))).all()
    booked_hours = sum(b.hours for b in week_bookings)
    n_studios = Studio.query.filter_by(is_active=True).count()
    capacity = n_studios * 12 * 7
    occupancy = round(booked_hours / capacity * 100) if capacity else 0

    # Balansi kam ustozlar (paket tugayapti — qayta sotuv imkoni)
    low_balance = []
    for t in Teacher.query.filter_by(is_active=True).all():
        bal = t.balance_hours()
        if 0 < t.hours_purchased() and bal <= 2:
            low_balance.append({"t": t.to_dict(), "balance": bal})
    low_balance.sort(key=lambda x: x["balance"])

    studios = {s.id: s for s in Studio.query.all()}
    teachers = {t.id: t for t in Teacher.query.all()}
    rows = [{
        "b": b.to_dict(),
        "studio": studios.get(b.studio_id).name if studios.get(b.studio_id) else "?",
        "teacher": teachers.get(b.teacher_id).name if teachers.get(b.teacher_id) else "?",
    } for b in todays]

    return render_template(
        "dashboard.html", todays=rows,
        kpi={
            "today_count": len(todays),
            "month_revenue": month_revenue,
            "month_pending": month_pending,
            "occupancy": occupancy,
            "booked_hours": round(booked_hours, 1),
            "studios": n_studios,
            "low_balance": len(low_balance),
        },
        low_balance=low_balance[:8], today=today)
