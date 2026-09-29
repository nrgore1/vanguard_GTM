"""Keeps the documentation honest: fails when code and docs drift apart."""
import re
from pathlib import Path

from vanguard import __version__
from vanguard.registry import Property

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SRC = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "vanguard").rglob("*.py"))
MANUAL = (DOCS / "PROGRAMMERS_MANUAL.md").read_text(encoding="utf-8")
DESIGN = (DOCS / "DESIGN.md").read_text(encoding="utf-8")
CASES = (DOCS / "TEST_CASES.md").read_text(encoding="utf-8")


def test_every_cli_command_is_in_the_manual():
    cmds = re.findall(r'sub\.add_parser\("([\w-]+)"', (ROOT / "vanguard" / "cli.py").read_text(encoding="utf-8"))
    assert len(cmds) >= 12
    missing = [c for c in cmds if f"vanguard {c}" not in MANUAL]
    assert not missing, f"document these commands in PROGRAMMERS_MANUAL §4: {missing}"


def test_every_env_var_is_in_the_manual():
    names = set(re.findall(r'(?:getenv|\bg)\("([A-Z_]+)"', SRC)) | set(re.findall(r'environ\["([A-Z_]+)"\]', SRC))
    missing = sorted(n for n in names if f"`{n}`" not in MANUAL and n not in MANUAL)
    assert not missing, f"document these env vars in PROGRAMMERS_MANUAL §3.1: {missing}"


def test_every_registry_field_is_documented():
    missing = [f for f in Property.model_fields
               if f not in ("revenue_target_usd", "campaign_days", "market") and f"`{f}`" not in MANUAL]
    assert not missing, f"document these properties.yaml fields in PROGRAMMERS_MANUAL §3.2: {missing}"


def test_test_ids_match_the_catalogue():
    py = (ROOT / "tests" / "test_e2e.py").read_text(encoding="utf-8") + (ROOT / "tests" / "test_web.py").read_text(encoding="utf-8")
    in_code = set(re.findall(r'"""((?:E2E|WEB)-L?\d+):', py))
    in_code |= set(re.findall(r'test\("(UI-\d+) ', (ROOT / "ui" / "e2e" / "app.spec.ts").read_text(encoding="utf-8")))
    in_docs = set(re.findall(r"^\| ((?:E2E|WEB|UI)-L?\d+) \|", CASES, re.M))
    assert in_code == in_docs, f"only in code: {in_code - in_docs}; only in docs: {in_docs - in_code}"


def test_versions_and_change_log_are_current():
    for name, text in (("DESIGN", DESIGN), ("MANUAL", MANUAL), ("TEST_CASES", CASES),
                       ("CHANGELOG", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))):
        assert __version__ in text, f"{name} does not mention version {__version__}"
    assert re.search(rf"^\| {re.escape(__version__)} \|", DESIGN, re.M), "add a DESIGN §17 change-log row"


def test_every_python_package_is_in_the_build():
    """A non-editable install (the Docker image) only ships packages listed in pyproject.toml."""
    import tomllib
    listed = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"])
    on_disk = {".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "vanguard").rglob("__init__.py")}
    assert on_disk <= listed, f"add these to [tool.setuptools] packages in pyproject.toml: {sorted(on_disk - listed)}"
