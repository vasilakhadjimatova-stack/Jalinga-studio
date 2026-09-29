"""Mijoz so'rovnomasi — ochiq sahifa (login'siz, maxfiy token = kalit)."""
from flask import Blueprint, render_template, request, abort

from core.feedback import apply_answers
from database import db
from models.billing import Teacher
from models.feedback import Survey, RATING_QUESTIONS, LOW_THRESHOLD
from models.studio import Booking, Studio

bp = Blueprint("feedback", __name__)


def _survey_or_404(token):
    token = (token or "").strip()
    if len(token) < 16:
        abort(404)
    s = Survey.query.filter_by(token=token).first()
    if not s:
        abort(404)
    return s


def _ctx(s):
    b = db.session.get(Booking, s.booking_id)
    st = db.session.get(Studio, b.studio_id) if b else None
    t = db.session.get(Teacher, s.teacher_id)
    return {"s": s, "b": b, "studio": st.name if st else "",
            "name": (t.name.split()[0] if t and t.name else ""),
            "questions": RATING_QUESTIONS, "low": LOW_THRESHOLD}


@bp.route("/survey/<token>", methods=["GET", "POST"])
def survey(token):
    s = _survey_or_404(token)
    if s.status == "done":
        return render_template("survey_done.html", again=True, **_ctx(s))
    err = None
    if request.method == "POST":
        err = apply_answers(s, request.form)
        if not err:
            return render_template("survey_done.html", again=False, **_ctx(s))
    return render_template("survey.html", err=err, form=request.form,
                           **_ctx(s))
