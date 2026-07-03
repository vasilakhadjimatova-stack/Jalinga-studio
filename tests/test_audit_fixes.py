"""Audit tuzatishlari: moliya-auth, to'lov sinxron, montaj yetim karta,
inf/nan, dedup label, qidiruv, portal reschedule."""


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _mk_client(app, name, hours=0, phone=""):
    from models.billing import Teacher, Payment
    from core.timeutils import today_iso
    from database import db
    with app.app_context():
        t = Teacher(name=name, phone=phone)
        db.session.add(t); db.session.flush()
        if hours:
            db.session.add(Payment(teacher_id=t.id, kind="package",
                                   hours=hours, amount=hours * 250000,
                                   date=today_iso(), is_paid=True))
        db.session.commit()
        return t.id


def _operator_client(app):
    """Admin bo'lmagan (operator) sifatida kirgan client."""
    from models.user import User
    from database import db
    with app.app_context():
        if not User.query.filter_by(code="220022").first():
            db.session.add(User(name="Operator X", code="220022",
                                role="operator", is_active=True))
            db.session.commit()
    c = __import__("app").app.test_client()
    c.post("/login", data={"code": "220022"})
    return c


# ── Moliya toggle endi admin-only ──
def test_finance_toggle_admin_only(app, admin_client, post):
    from models.billing import Payment
    from database import db
    tid = _mk_client(app, "Fin Mijoz")
    with app.app_context():
        p = Payment(teacher_id=tid, kind="hourly", amount=100000, hours=0,
                    date="2027-05-01", is_paid=False)
        db.session.add(p); db.session.commit()
        pid = p.id
    op = _operator_client(app)
    with op.session_transaction() as s:
        s["_csrf"] = "t"
    r = op.post(f"/finance/{pid}/toggle", data={"_csrf": "t"})
    # operator → dashboardга yo'naltiriladi, o'zgarmaydi
    with app.app_context():
        assert Payment.query.get(pid).is_paid is False
    # admin → ishlaydi
    post(admin_client, f"/finance/{pid}/toggle")
    with app.app_context():
        assert Payment.query.get(pid).is_paid is True


# ── Edit to'langan to'lovni ham yangilaydi ──
def test_edit_updates_paid_payment(app, admin_client, post):
    from models.studio import Booking, Studio
    from models.billing import Payment
    from database import db
    tid = _mk_client(app, "EditPaid Mijoz")
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="existing",
         teacher_id=tid, date="2027-06-01", start="10:00", end="12:00",
         pay_type="hourly")
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        bid = b.id
        rate = Studio.query.get(sid).hourly_rate
        p = Payment.query.filter_by(booking_id=bid).first()
        p.is_paid = True                    # to'langan qilib qo'yamiz
        db.session.commit()
    # 2 soatdan 4 soatga ko'chiramiz
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date="2027-06-02", start="09:00", end="13:00")
    with app.app_context():
        p = Payment.query.filter_by(booking_id=bid).first()
        assert p.amount == round(4 * rate)   # to'langan bo'lsa ham yangilandi
        assert p.date == "2027-06-02"


# ── Bekorда to'langan to'lov saqlanadi (arvoh emas) ──
def test_cancel_keeps_paid_payment(app, admin_client, post):
    from models.studio import Booking
    from models.billing import Payment
    from database import db
    tid = _mk_client(app, "CancelPaid Mijoz")
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="existing",
         teacher_id=tid, date="2027-07-01", start="10:00", end="12:00",
         pay_type="hourly")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
        p = Payment.query.filter_by(booking_id=bid).first()
        p.is_paid = True
        db.session.commit()
    post(admin_client, f"/bookings/{bid}/status", status="cancelled")
    with app.app_context():
        # to'langan to'lov o'chmadi (haqiqiy pul)
        assert Payment.query.filter_by(booking_id=bid, is_paid=True).count() == 1


# ── done→noshow montaj kartasini o'chiradi ──
def test_done_to_noshow_removes_editjob(app, admin_client, post):
    from models.studio import Booking
    from models.montaj import EditJob
    tid = _mk_client(app, "Montaj Mijoz")
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="existing",
         teacher_id=tid, date="2027-08-01", start="10:00", end="12:00",
         pay_type="hourly")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
    post(admin_client, f"/bookings/{bid}/status", status="done")
    with app.app_context():
        assert EditJob.query.filter_by(booking_id=bid).count() == 1
    post(admin_client, f"/bookings/{bid}/status", status="noshow")
    with app.app_context():
        assert EditJob.query.filter_by(booking_id=bid).count() == 0   # yetim qolmadi


# ── buy_package inf/nan ni rad etadi ──
def test_buy_package_rejects_infinity(app, admin_client, post):
    from models.billing import Teacher
    tid = _mk_client(app, "Inf Mijoz")
    post(admin_client, f"/teachers/{tid}/package", hours="inf",
         amount="1000000", method="naqd")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 0   # yaratilmadi


# ── Inline dedup: mavjud topilsa "yangi mijoz" deb yolg'on chiqmaydi ──
def test_inline_dedup_no_false_new_flash(app, admin_client, post):
    from models.billing import Teacher
    _mk_client(app, "Aniq Mijoz", phone="+998901239999")
    sid = _sid(app)
    r = post(admin_client, "/bookings/save", studio_id=sid, client_mode="new",
             new_name="Boshqa Nom", new_phone="+998901239999",
             date="2027-09-01", start="10:00", end="12:00", pay_type="hourly")
    # yangi Teacher yaratilmadi
    with app.app_context():
        assert Teacher.query.filter_by(name="Boshqa Nom").count() == 0
    # follow → flashда "yangi mijoz" bo'lmasligi kerak
    html = admin_client.get("/calendar").data.decode()
    assert "yangi mijoz qo'shildi" not in html


# ── Mijoz qidiruv/filtr ──
def test_client_search_filter(app, admin_client):
    _mk_client(app, "Qidiruv Test Alfa", phone="+998905550001")
    _mk_client(app, "Boshqa Beta", phone="+998905550002")
    html = admin_client.get("/teachers?q=Alfa").data.decode()
    assert "Qidiruv Test Alfa" in html
    assert "Boshqa Beta" not in html


# ── Portal reschedule ──
def test_portal_reschedule(app, admin_client, post):
    from models.studio import Booking
    from models.billing import Teacher
    from database import db
    from datetime import timedelta
    from core.timeutils import now_tashkent
    tid = _mk_client(app, "Portal Mijoz")
    with app.app_context():
        t = Teacher.query.get(tid)
        t.ensure_token(); db.session.commit()
        token = t.portal_token
    sid = _sid(app)
    # 3 kundan keyingi bron (24 soatдан ko'p) — portal ko'chira oladi
    d = (now_tashkent() + timedelta(days=3)).strftime("%Y-%m-%d")
    d2 = (now_tashkent() + timedelta(days=4)).strftime("%Y-%m-%d")
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="existing",
         teacher_id=tid, date=d, start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf"] = "t"
    c.post(f"/my/{token}/reschedule/{bid}",
           data={"date": d2, "start": "14:00", "hours": "2"})
    with app.app_context():
        b = Booking.query.get(bid)
        assert b.date == d2 and b.start == "14:00"
