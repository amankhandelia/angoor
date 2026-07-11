"""Shared pytest fixtures and environment configuration for angoor tests."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Force a unified terminal environment so that snapshot/visual comparisons are
# stable across local macOS, Linux, and headless CI runs (per the Textual test
# guidelines).
os.environ.setdefault("TERM", "xterm-256color")
os.environ.setdefault("COLORTERM", "truecolor")
os.environ.setdefault("TEXTUAL_WIDTH", "120")
os.environ.setdefault("TEXTUAL_HEIGHT", "40")

DATA_DIR = Path(__file__).parent / "data"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Async tests are auto-discovered thanks to asyncio_mode=auto in
    # pyproject.toml; nothing to do here, but keep the hook in case we
    # want to add filtering later.
    return None


@pytest.fixture
def sample_csv() -> Path:
    """Path to a small, deterministic CSV fixture."""
    return DATA_DIR / "sample.csv"


@pytest.fixture
def sample_tsv() -> Path:
    """Path to a small tab-separated fixture."""
    return DATA_DIR / "sample.tsv"


@pytest.fixture
def sample_parquet() -> Path:
    """Path to a small, deterministic Parquet fixture (generated via DuckDB)."""
    return DATA_DIR / "sample.parquet"


@pytest.fixture
def missing_path(tmp_path: Path) -> Path:
    """A path that does not exist on disk."""
    return tmp_path / "does_not_exist.csv"


@pytest.fixture
def unsupported_path(tmp_path: Path) -> Path:
    """A path with an unsupported extension that *does* exist."""
    p = tmp_path / "data.xlsx"
    p.write_text("not really an xlsx")
    return p


@pytest.fixture
def clipboard(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ViewerApp.copy_to_clipboard with a mock that records calls.

    Returns the mock; inspect with ``clipboard.call_args_list``.
    """
    from angoor.app import ViewerApp

    mock = MagicMock()
    monkeypatch.setattr(ViewerApp, "copy_to_clipboard", mock)
    return mock


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list:
    """Record every `app.notify(...)` call instead of pushing real notifications.

    Each entry is a dict of the kwargs passed to `notify`.
    """
    from angoor.app import ViewerApp

    calls: list[dict] = []

    def fake_notify(self, message, *args, **kwargs):
        calls.append({"message": message, **kwargs})
        return None

    monkeypatch.setattr(ViewerApp, "notify", fake_notify)
    return calls