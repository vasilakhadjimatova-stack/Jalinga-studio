"""Analitika: heatmap/churn sahifasi + bonus soatlar."""


def test_analytics_renders(admin_client):
    r = admin_client.get("/analytics")
    assert r.status_code == 200
    assert "Bandlik xaritasi".encode() in r.data
    assert b"Churn radar" in r.data


def test_bonus_hours(app, admin_client, post):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="Bonus Ustoz"); db.session.add(t); db.session.commit()
        tid = t.id
    r = post(admin_client, f"/teachers/{tid}/bonus", hours="2", reason="Referral")
    assert r.status_code in (302, 303)
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 2
    # 20 dan ortiq — rad
    post(admin_client, f"/teachers/{tid}/bonus", hours="50", reason="x")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 2


def test_churn_lists_inactive_teacher(app, admin_client):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="Churn Nomzod X"); db.session.add(t); db.session.commit()
    r = admin_client.get("/analytics")
    assert b"Churn Nomzod X" in r.data   # hech yozilmagan -> radar ro'yxatida


# ── Yangi strategik analitika (KPI/trend/segment/insight/SLA) ──

def test_analytics_new_sections(admin_client):
    r = admin_client.get("/analytics")
    assert r.status_code == 200
    for text in ("Aqlli xulosalar", "6 oylik trend", "Kelgusi 7 kun",
                 "Mijoz segmentlari", "Top mijozlar"):
        assert text.encode() in r.data, text


def test_analytics_admin_sees_money(admin_client):
    r = admin_client.get("/analytics")
    assert "Tushum (oy)".encode() in r.data


def test_analytics_operator_no_money(app):
    """Operator analitikani ko'radi, lekin pul ko'rsatkichlarisiz."""
    from models.user import User
    from database import db
    with app.app_context():
        u = User.query.filter_by(code="333333").first()
        if u is None:
            u = User(name="OpA", code="333333", role="operator")
            db.session.add(u)
            db.session.commit()
    c = app.test_client()
    c.post("/login", data={"code": "333333"})
    r = c.get("/analytics")
    assert r.status_code == 200
    assert "Tushum (oy)".encode() not in r.data
    assert "Aqlli xulosalar".encode() in r.data
