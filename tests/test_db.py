"""Database layer: SQL translation for PostgreSQL and selecting the engine from VANGUARD_DATABASE_URL.

The whole suite also runs against PostgreSQL when VANGUARD_TEST_DATABASE_URL is set (see conftest.py)."""
from vanguard.db import Database, is_postgres_url, split_script, to_pg_ddl, to_pg_params


def test_placeholders_and_percent_signs():
    assert to_pg_params("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
    assert to_pg_params("SELECT '100%' AS x, name FROM t WHERE name LIKE ?") == \
        "SELECT '100%%' AS x, name FROM t WHERE name LIKE %s"
    assert to_pg_params("SELECT 'what?' AS q FROM t WHERE id=?") == "SELECT 'what?' AS q FROM t WHERE id=%s"


def test_ddl_translation():
    ddl = ("CREATE TABLE IF NOT EXISTS audit_log (\n  id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL\n);\n"
           "CREATE TABLE IF NOT EXISTS tasks (\n  run_id TEXT\n);")
    out = to_pg_ddl(ddl)
    assert "BIGSERIAL PRIMARY KEY" in out and "DOUBLE PRECISION" in out and "AUTOINCREMENT" not in out
    assert "tasks (\n  rowid BIGSERIAL," in out and "audit_log (\n  rowid" not in out
    assert len(split_script(out)) == 2


def test_engine_selection(tmp_path, monkeypatch):
    monkeypatch.delenv("VANGUARD_DATABASE_URL", raising=False)
    assert not Database(tmp_path / "a.db").postgres
    assert Database(tmp_path / "a.db", "sqlite:///" + str(tmp_path / "b.db")).path.name == "b.db"
    assert is_postgres_url("postgresql://u:p@h:5432/d") and is_postgres_url("postgres://h/d")
    assert "***" in Database(None, "postgresql://user:secret@h:5432/d").describe()
    assert "secret" not in Database(None, "postgresql://user:secret@h:5432/d").describe()
