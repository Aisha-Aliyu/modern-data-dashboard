import importlib
import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def dashboard(tmp_path_factory):
    """Import the app against a throwaway SQLite database."""
    db_file = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DASH_DB_URI"] = f"sqlite:///{db_file}"
    os.environ["DASH_JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256"
    # Empty rather than removed, so a local backend/.env can't switch real email on
    # (python-dotenv leaves variables that are already set alone)
    for name in ("DASH_SMTP_HOST", "DASH_SMTP_USER", "DASH_SMTP_PASS",
                 "MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD"):
        os.environ[name] = ""
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    module = importlib.import_module("app")
    yield module
    module.scheduler.shutdown(wait=False)


@pytest.fixture()
def client(dashboard):
    dashboard.reset_rate_limits()
    return dashboard.app.test_client()
