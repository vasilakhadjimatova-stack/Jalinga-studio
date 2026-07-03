import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_TMP = tempfile.mkdtemp(prefix="jalinga_test_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "t.db").replace("\\", "/")
os.environ["SECRET_KEY"] = "pytest-secret"
os.environ["ADMIN_CODE"] = "111111"

import pytest  # noqa: E402

from app import app as _app  # noqa: E402
from database import db  # noqa: E402


@pytest.fixture(scope="session")
def app():
    _app.config.update(TESTING=True)
    return _app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app):
    c = app.test_client()
    c.post("/login", data={"code": "111111"})
    return c


@pytest.fixture()
def post(app):
    """CSRF avto-qo'shadigan POST yordamchisi."""
    def _post(client, url, **data):
        with client.session_transaction() as s:
            s["_csrf"] = "testtoken"
        data.setdefault("_csrf", "testtoken")
        return client.post(url, data=data)
    return _post
