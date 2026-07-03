"""Montaj kanban — yozildi → montajda → tekshiruvda → topshirildi.

Har karta: dars, ustoz, montajchi, SLA muddati. Topshirilganda ustozga
Telegram xabar (havola bilan) ketadi. Kechikkanlar qizil belgilanadi.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, current_user
from database import db
from models.montaj import EditJob, EDIT_STATUSES, EDIT_LABELS
from models.billing import Teacher
from models.user import User

bp = Blueprint("montaj", __name__)


@bp.route("/montaj")
@login_required
def index():
    jobs = EditJob.query.order_by(EditJob.updated_at.desc()).limit(300).all()
    tmap = {t.id: t.name for t in Teacher.query.all()}
    umap = {u.id: u.name for u in User.query.all()}
    cols = {s: [] for s in EDIT_STATUSES}
    for j in jobs:
        d = j.to_dict()
        d["teacher_name"] = tmap.get(j.teacher_id, "?")
        d["assignee_name"] = umap.get(j.assignee_id, "") if j.assignee_id else ""
        cols.setdefault(j.status, []).append(d)
    # Kechikkanlar tepada
    for s in cols:
        cols[s].sort(key=lambda x: (not x["overdue"], x["due_date"] or "9999"))
    # Jamoa ish yuki (topshirilmagan kartalar montajchi bo'yicha)
    workload = {}
    for j in jobs:
        if j.status != "delivered" and j.assignee_id:
            nm = umap.get(j.assignee_id, "?")
            workload[nm] = workload.get(nm, 0) + 1
    team = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    overdue_n = sum(1 for j in jobs if j.is_overdue())
    return render_template(
        "montaj.html", cols=cols, statuses=EDIT_STATUSES, labels=EDIT_LABELS,
        team=[u.to_dict() for u in team], workload=workload,
        open_n=sum(1 for j in jobs if j.status != "delivered"),
        overdue_n=overdue_n)


@bp.route("/montaj/<int:jid>/move", methods=["POST"])
@login_required
def move(jid):
    j = EditJob.query.get_or_404(jid)
    new = (request.form.get("status") or "").strip()
    if new not in EDIT_STATUSES:
        flash("Holat noto'g'ri", "error")
        return redirect(url_for("montaj.index"))
    j.status = new
    if new == "delivered":
        j.delivered_at = datetime.utcnow()
        j.link = (request.form.get("link") or j.link or "").strip()[:400]
        # Ustozga xushxabar (TG ulangan bo'lsa)
        try:
            from core.telegram import tg_send
            t = Teacher.query.get(j.teacher_id)
            if t and t.tg_chat_id:
                msg = (f"🎉 <b>Yozuvingiz tayyor!</b>\n{j.title}")
                if j.link:
                    msg += f"\n🔗 {j.link}"
                tg_send(t.tg_chat_id, msg)
        except Exception:
            pass
    db.session.commit()
    flash(f"→ {EDIT_LABELS.get(new, (new,))[0]}", "success")
    return redirect(url_for("montaj.index"))


@bp.route("/montaj/<int:jid>/assign", methods=["POST"])
@login_required
def assign(jid):
    j = EditJob.query.get_or_404(jid)
    try:
        uid = int(request.form.get("assignee_id") or 0)
    except (ValueError, TypeError):
        uid = 0
    j.assignee_id = uid or None
    due = (request.form.get("due_date") or "").strip()[:10]
    if due:
        j.due_date = due
    db.session.commit()
    flash("✅ Biriktirildi", "success")
    return redirect(url_for("montaj.index"))
