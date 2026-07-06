"""Ikkinchi audit (32 topilma) tuzatishlari uchun regressiya testlari."""
from datetime import timedelta

from core.timeutils import now_tashkent


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _mk_teacher(app, name="AV Mijoz", **kw):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name=name, is_active=True, **kw)
        db.session.add(t); db.session.commit()
        return t.id


def _future(days):
    return (now_tashkent().date() + timedelta(days=days)).strftime("%Y-%m-%d")


# ── Moliya: inf/nan + sana validatsiya ──
def test_finance_rejects_inf_nan(app, admin_client, post):
    from models.finance import FinTransaction
    import math
    for bad in ("nan", "inf", "1e999", "-5", "0"):
        post(admin_client, "/finance/transactions/add",
             date="2026-07-10", category="Поступление от клиента (запись)",
             wallet="Наличные", amount=bad)
    with app.app_context():
        assert all(math.isfinite(t.amount) and t.amount > 0
                   for t in FinTransaction.query.all())


def test_finance_rejects_bad_date(app, admin_client, post):
    from models.finance import FinTransaction
    r = post(admin_client, "/finance/transactions/add",
             date="1234-56-78", category="Поступление от клиента (запись)",
             wallet="Наличные", amount="1000")
    assert r.status_code in (302, 303)   # 500 emas
    with app.app_context():
        assert all(1 <= t.month <= 12 for t in FinTransaction.query.all())
    assert admin_client.get("/finance").status_code == 200
    assert admin_client.get("/finance/dds").status_code == 200


# ── Paket: to'lanmagan paket balans bermaydi ──
def test_unpaid_package_no_balance(app, admin_client, post):
    from database import db
    from models.billing import Teacher, Payment
    tid = _mk_teacher(app, "Unpaid Paket")
    with app.app_context():
        db.session.add(Payment(teacher_id=tid, kind="package", hours=10,
                               amount=2500000, date=_future(0), is_paid=False))
        db.session.commit()
        assert Teacher.query.get(tid).balance_hours() == 0   # to'lanmagan → 0
        p = Payment.query.filter_by(teacher_id=tid).first()
        p.is_paid = True
        db.session.commit()
        assert Teacher.query.get(tid).balance_hours() == 10  # to'landi → 10


# ── set_status: reaktivatsiyada konflikt ──
def test_reactivate_conflict_blocked(app, admin_client, post):
    from models.studio import Booking
    sid = _sid(app)
    t1 = _mk_teacher(app, "React A")
    t2 = _mk_teacher(app, "React B")
    day = _future(20)
    post(admin_client, "/bookings/save", client_mode="existing", studio_id=sid,
         teacher_id=t1, date=day, start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=t1, date=day).first().id
    post(admin_client, f"/bookings/{bid}/status", status="cancelled")
    post(admin_client, "/bookings/save", client_mode="existing", studio_id=sid,
         teacher_id=t2, date=day, start="10:00", end="12:00", pay_type="hourly")
    post(admin_client, f"/bookings/{bid}/status", status="active")
    with app.app_context():
        assert Booking.query.get(bid).status == "cancelled"   # qaytmadi


# ── Manual chegirma tahrirdan keyin ham saqlanadi ──
def test_manual_discount_survives_edit(app, admin_client, post):
    from models.studio import Booking, Studio
    from models.billing import Payment
    sid = _sid(app)
    tid = _mk_teacher(app, "Disc Edit")
    day = _future(21)
    post(admin_client, "/bookings/save", client_mode="existing", studio_id=sid,
         teacher_id=tid, date=day, start="16:00", end="18:00",
         pay_type="hourly", discount="40")
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        rate = Studio.query.get(sid).hourly_rate
        assert b.discount == 40
        bid = b.id
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date=_future(22), start="16:00", end="18:00")
    with app.app_context():
        p = Payment.query.filter_by(booking_id=bid).first()
        assert p.amount == round(2 * rate * 0.6)   # 40% chegirma saqlandi


# ── Teacher: yangi faol, tahrirda arxivlash ──
def test_new_client_active_edit_can_archive(app, admin_client, post):
    from models.billing import Teacher
    post(admin_client, "/teachers/save", name="Arxiv Test")
    with app.app_context():
        t = Teacher.query.filter_by(name="Arxiv Test").first()
        assert t.is_active is True   # yangi → faol
        tid = t.id
    # tahrir: is_active yubormaymiz → arxivlanadi
    post(admin_client, "/teachers/save", id=str(tid), name="Arxiv Test")
    with app.app_context():
        assert Teacher.query.get(tid).is_active is False


# ── best_discount: eng katta qoida ──
def test_best_discount_picks_max(app):
    from database import db
    from models.pricing import PriceRule, best_discount
    sid = _sid(app)
    with app.app_context():
        PriceRule.query.delete()
        db.session.add(PriceRule(studio_id=None, name="A", days="",
                                 start_hour=9, end_hour=14, discount=15,
                                 is_active=True))
        db.session.add(PriceRule(studio_id=None, name="B", days="",
                                 start_hour=9, end_hour=14, discount=30,
                                 is_active=True))
        db.session.commit()
        wd = (now_tashkent().date() + timedelta(days=7))
        while wd.weekday() != 0:
            wd += timedelta(days=1)
        assert best_discount(sid, wd.strftime("%Y-%m-%d"), "10:00")[0] == 30
        PriceRule.query.delete(); db.session.commit()


# ── dmy filtri ──
def test_dmy_filter(app):
    dmy = app.jinja_env.filters["dmy"]
    assert dmy("2026-07-10") == "10.07.2026"
    assert dmy("2026-07-10 14:30") == "10.07.2026 14:30"   # vaqt saqlanadi
    assert dmy("naqd") == "naqd"                            # non-date o'zgarmaydi
    assert dmy("") == ""


# ── ADMIN_CODE band bo'lsa admin kodi o'zgarmaydi ──
def test_admin_code_taken_by_other_no_change(app):
    import os
    from database import db
    from models.user import User
    from seed import seed_all
    old = os.environ.get("ADMIN_CODE")
    try:
        with app.app_context():
            db.session.add(User(name="Op", code="902413", role="operator"))
            db.session.commit()
            os.environ["ADMIN_CODE"] = "902413"   # boshqada band
            seed_all()
            admin = User.query.filter_by(role="admin").order_by(User.id).first()
            assert admin.code != "902413"          # o'zgarmadi
            assert User.query.filter_by(code="902413").count() == 1
    finally:
        with app.app_context():
            u = User.query.filter_by(code="902413", role="operator").first()
            if u:
                db.session.delete(u); db.session.commit()
        if old is None:
            os.environ.pop("ADMIN_CODE", None)
        else:
            os.environ["ADMIN_CODE"] = old


# ── Ochiq bron: MAX_UPCOMING + 60 kun chegarasi ──
def test_public_booking_max_days(app, client):
    from models.studio import Booking
    sid = _sid(app)
    far = (now_tashkent().date() + timedelta(days=70)).strftime("%Y-%m-%d")
    client.post("/book/submit", data={
        "name": "Uzoq", "phone": "+998900001122", "studio_id": sid,
        "date": far, "start": "10:00", "hours": "1"})
    with app.app_context():
        assert Booking.query.filter_by(date=far).count() == 0


def test_edit_paid_booking_updates_finance(app, admin_client, post):
    """To'langan bron uzaytirilса bog'langan moliya kirimi ham yangilanadi."""
    from models.studio import Booking, Studio
    from models.billing import Payment
    from models.finance import FinTransaction
    sid = _sid(app)
    tid = _mk_teacher(app, "PaidEdit")
    day = _future(25)
    post(admin_client, "/bookings/save", client_mode="existing", studio_id=sid,
         teacher_id=tid, date=day, start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        bid, rate = b.id, Studio.query.get(sid).hourly_rate
        pid = Payment.query.filter_by(booking_id=bid).first().id
    post(admin_client, f"/finance/{pid}/pay", wallet="Наличные", method="naqd")
    # 2 → 4 soatga uzaytirish
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date=day, start="10:00", end="14:00")
    with app.app_context():
        tx = FinTransaction.query.filter_by(payment_id=pid,
                                            source="studio").first()
        assert tx is not None and tx.amount == round(4 * rate)   # yangilandi
