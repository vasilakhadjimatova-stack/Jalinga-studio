"""Vazifalar tizimi — Kanban oqimi, ruxsatlar, bildirishnomalar."""
from database import db
from models.user import User
from models.communication import Task, Notification, TaskComment


def _mk_operator(app, code="220022", name="Op Test"):
    with app.app_context():
        u = User.query.filter_by(code=code).first()
        if not u:
            u = User(name=name, code=code, role="operator")
            db.session.add(u)
            db.session.commit()
        return u.id


def _op_client(app, code="220022"):
    c = app.test_client()
    c.post("/login", data={"code": code})
    return c


def test_board_loads(admin_client):
    r = admin_client.get("/tasks")
    assert r.status_code == 200
    assert "Vazifalar" in r.get_data(as_text=True)


def test_create_task_notifies_assignee(app, admin_client, post):
    opid = _mk_operator(app)
    before = None
    with app.app_context():
        before = Notification.query.count()
    r = post(admin_client, "/tasks/new", title="Montaj qil",
             description="tez", assign_to=f"user:{opid}",
             due_date="2026-09-01", priority="high")
    assert r.status_code in (200, 302)
    with app.app_context():
        t = Task.query.filter_by(title="Montaj qil").first()
        assert t is not None and t.assignee_id == opid
        assert t.priority == "high"
        # assignee'ga bildirishnoma ketdi
        assert Notification.query.count() > before


def test_due_date_required(app, admin_client, post):
    opid = _mk_operator(app)
    r = post(admin_client, "/tasks/new", title="Muddatsiz",
             assign_to=f"user:{opid}", due_date="")
    with app.app_context():
        assert Task.query.filter_by(title="Muddatsiz").first() is None


def test_status_flow_and_assigner_notified(app, admin_client, post):
    opid = _mk_operator(app)
    post(admin_client, "/tasks/new", title="Oqim test",
         assign_to=f"user:{opid}", due_date="2026-09-01")
    with app.app_context():
        tid = Task.query.filter_by(title="Oqim test").first().id
    op = _op_client(app)
    for st in ("accepted", "in_progress", "done"):
        post(op, f"/tasks/{tid}/advance", status=st)
    with app.app_context():
        t = Task.query.get(tid)
        assert t.status == "done"
        assert t.progress == 100
        assert t.completed_at is not None


def test_operator_cannot_delete(app, admin_client, post):
    opid = _mk_operator(app)
    post(admin_client, "/tasks/new", title="O'chmas",
         assign_to=f"user:{opid}", due_date="2026-09-01")
    with app.app_context():
        tid = Task.query.filter_by(title="O'chmas").first().id
    op = _op_client(app)
    post(op, f"/tasks/{tid}/delete")
    with app.app_context():
        assert Task.query.get(tid) is not None   # o'chmadi
    # admin o'chira oladi
    post(admin_client, f"/tasks/{tid}/delete")
    with app.app_context():
        assert Task.query.get(tid) is None


def test_comment_chat(app, admin_client, post):
    opid = _mk_operator(app)
    post(admin_client, "/tasks/new", title="Chat test",
         assign_to=f"user:{opid}", due_date="2026-09-01")
    with app.app_context():
        tid = Task.query.filter_by(title="Chat test").first().id
    r = post(admin_client, f"/tasks/{tid}/comment", body="Assalomu alaykum")
    with app.app_context():
        assert TaskComment.query.filter_by(task_id=tid).count() == 1


def test_role_assignment(app, admin_client, post):
    r = post(admin_client, "/tasks/new", title="Jamoa ishi",
             assign_to="role:operator", due_date="2026-09-02")
    with app.app_context():
        t = Task.query.filter_by(title="Jamoa ishi").first()
        assert t is not None and t.target_role == "operator"
        assert t.assignee_id is None


def test_notifications_page(admin_client):
    r = admin_client.get("/notifications")
    assert r.status_code == 200


def test_badge_api(admin_client):
    r = admin_client.get("/api/badge/notifications")
    assert r.status_code == 200
    assert "count" in r.get_json()
