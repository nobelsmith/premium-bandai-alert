from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def api_search_page(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "api_search_page.json").read_text(encoding="utf-8"))


@pytest.fixture
def series_page_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "series_page.html").read_text(encoding="utf-8")


@pytest.fixture
def series_page_no_preload_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "series_page_no_preload.html").read_text(encoding="utf-8")
