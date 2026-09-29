"""Run the whole suite against PostgreSQL by setting VANGUARD_TEST_DATABASE_URL to a server you can
create databases on, e.g. postgresql://postgres@127.0.0.1:5432/postgres. Each test gets a fresh database.
Without it, tests use SQLite files in pytest's temp folders."""
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

ADMIN_URL = os.getenv("VANGUARD_TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _fresh_postgres(monkeypatch):
    if not ADMIN_URL:
        yield
        return
    import psycopg
    name = "vgtest_" + uuid.uuid4().hex[:10]
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    parts = urlsplit(ADMIN_URL)
    monkeypatch.setenv("VANGUARD_DATABASE_URL", urlunsplit(parts._replace(path="/" + name)))
    yield
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
