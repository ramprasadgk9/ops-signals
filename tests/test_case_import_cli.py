from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import create_engine, func, select

from backend.app.models.entities import OperationalCaseEntity
from intelligence.cli import build_parser
from backend.app.case_import.cli import run

FIXTURES = Path(__file__).parent / "fixtures" / "case_import"
TEMPLATES = Path(__file__).resolve().parents[1] / "backend" / "app" / "case_import" / "templates"


def _case_count(url: str) -> int:
    engine = create_engine(url)
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(OperationalCaseEntity)).scalar()


def test_import_cases_folder_is_idempotent(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "exports"
    (folder / "postmortems").mkdir(parents=True)
    shutil.copy(FIXTURES / "jira-export.csv", folder)
    shutil.copy(TEMPLATES / "example-postmortem.md", folder / "postmortems")
    url = f"sqlite+pysqlite:///{tmp_path / 'ops.db'}"

    def import_cases(*extra: str) -> int:
        args = build_parser().parse_args(["import-cases", str(folder), "--database-url", url, "--no-index", *extra])
        return run(args)

    assert import_cases("--dry-run") == 0
    assert '"new": 3' in capsys.readouterr().out

    assert import_cases() == 0
    output = capsys.readouterr().out
    assert "skipped jira-export.csv row 4: missing root_cause" in output
    assert '"new": 3' in output
    assert _case_count(url) == 3

    assert import_cases() == 0
    assert '"unchanged": 3' in capsys.readouterr().out
    assert _case_count(url) == 3
