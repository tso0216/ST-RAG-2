import runpy
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = runpy.run_path(str(ROOT / "scripts" / "db" / "create_main_db.py"))["SCHEMA"]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    yield c
    c.close()
