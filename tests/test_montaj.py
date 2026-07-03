"""Montaj kanban: avto-karta, oqim harakati, SLA/kechikish."""


def _mk_done_booking(app, admin_client, post, day="2026-09-01", start="10:00"):
    from models.studio import Booking
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name=f"Montaj Ustoz {day} {start}")
        db.session.add(t); db.session.commit()
        tid = t.id
        sid = __import__("models.studio", fromlist=["Studio"]).Studio.query.first().id
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date=day, start=start, end="12:00", pay_type="hourly")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid, date=day).first().id
    post(admin_client, f"/bookings/{bid}/status", status="done")
    return bid, tid


def test_done_booking_creates_edit_job(app, admin_client, post):
    from models.montaj import EditJob
    bid, _tid = _mk_done_booking(app, admin_client, post, day="2026-09-01")
    with app.app_context():
        j = EditJob.query.filter_by(booking_id=bid).first()
        assert j is not None
        assert j.status == "recorded"
        assert j.due_date          # SLA muddati qo'yildi
    # Ikkinchi marta "done" bosilsa — dublikat karta YARALMAYDI
    post(admin_client, f"/bookings/{bid}/status", status="done")
    with app.app_context():
        assert EditJob.query.filter_by(booking_id=bid).count() == 1


def test_kanban_move_flow(app, admin_client, post):
    from models.montaj import EditJob
    bid, _ = _mk_done_booking(app, admin_client, post, day="2026-09-02")
    with app.app_context():
        jid = EditJob.query.filter_by(booking_id=bid).first().id
    post(admin_client, f"/montaj/{jid}/move", status="editing")
    with app.app_context():
        assert EditJob.query.get(jid).status == "editing"
    post(admin_client, f"/montaj/{jid}/move", status="review")
    post(admin_client, f"/montaj/{jid}/move", status="delivered",
         link="https://youtu.be/xyz")
    with app.app_context():
        j = EditJob.query.get(jid)
        assert j.status == "delivered"
        assert j.delivered_at is not None
        assert j.link == "https://youtu.be/xyz"


def test_assign_and_overdue(app, admin_client, post):
    from models.montaj import EditJob
    from models.user import User
    bid, _ = _mk_done_booking(app, admin_client, post, day="2026-09-03")
    with app.app_context():
        jid = EditJob.query.filter_by(booking_id=bid).first().id
        uid = User.query.first().id
    post(admin_client, f"/montaj/{jid}/assign", assignee_id=uid,
         due_date="2020-01-01")   # o'tgan sana → kechikkan
    with app.app_context():
        j = EditJob.query.get(jid)
        assert j.assignee_id == uid
        assert j.is_overdue() is True
    # Topshirilgach kechikkan hisoblanmaydi
    post(admin_client, f"/montaj/{jid}/move", status="delivered")
    with app.app_context():
        assert EditJob.query.get(jid).is_overdue() is False


def test_kanban_page_renders(app, admin_client, post):
    _mk_done_booking(app, admin_client, post, day="2026-09-04")
    r = admin_client.get("/montaj")
    assert r.status_code == 200
    assert "Montaj oqimi".encode() in r.data
    assert b"Yozildi" in r.data
