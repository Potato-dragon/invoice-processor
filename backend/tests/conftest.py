"""Test setup: a separate database (invoice_test), fake LLM, inline pipeline.

Environment is set before any app module is imported, so app.db binds to the
test database and the dev data is never touched.
"""
import os

_base = os.environ.get("DATABASE_URL", "postgresql+psycopg://invoice:invoice@db:5432/invoice")
TEST_DB_URL = _base.rsplit("/", 1)[0] + "/invoice_test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["LLM_FAKE"] = "true"
os.environ["PIPELINE_SYNC"] = "true"
os.environ.setdefault("API_KEY", "test-key")
os.environ["STORAGE_DIR"] = "/tmp/invoice-test-storage"

import pytest  # noqa: E402


def _create_test_db() -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(_base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'invoice_test'")).first()
        if not exists:
            conn.execute(text("CREATE DATABASE invoice_test"))
    admin.dispose()


@pytest.fixture(scope="session")
def test_db():
    """Fresh schema via Alembic on the test database."""
    try:
        _create_test_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    eng = create_engine(TEST_DB_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    command.upgrade(cfg, "head")
    yield TEST_DB_URL
