"""Visual SVG snapshot tests for the ViewerApp.

These record the rendered terminal frame and compare it against a committed
"golden master" SVG in tests/snapshots/. If a layout/CSS change shifts the
rendered output, the test fails and the snapshot must be re-approved.

Regenerate / accept baselines with:

    uv run python -m pytest tests/test_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

from angoor.app import ViewerApp

TERMINAL_SIZE = (120, 40)


def _app(sample_csv: Path) -> ViewerApp:
    return ViewerApp(str(sample_csv))


def test_snapshot_initial_table_view(sample_csv, snap_compare):
    """The freshly mounted data table, cursor at the top-left cell."""
    assert snap_compare(_app(sample_csv), terminal_size=TERMINAL_SIZE)


def test_snapshot_after_navigation(sample_csv, snap_compare):
    """Cursor moved two rows down and one column right."""
    assert snap_compare(
        _app(sample_csv),
        press=["j", "j", "l"],
        terminal_size=TERMINAL_SIZE,
    )


def test_snapshot_last_row(sample_csv, snap_compare):
    """`G` parked the cursor on the final row."""
    assert snap_compare(
        _app(sample_csv),
        press=["G"],
        terminal_size=TERMINAL_SIZE,
    )


def test_snapshot_row_search_open(sample_csv, snap_compare):
    """`/wid` opens the row search bar with the seed visible."""
    assert snap_compare(
        _app(sample_csv),
        press=["/", "w", "i", "d"],
        terminal_size=TERMINAL_SIZE,
    )


def test_snapshot_column_search_open(sample_csv, snap_compare):
    """`//` opens the (empty) column search bar."""
    assert snap_compare(
        _app(sample_csv),
        press=["l", "l", "/", "/"],
        terminal_size=TERMINAL_SIZE,
    )


def test_snapshot_parquet_view(sample_parquet, snap_compare):
    """The Parquet fixture renders with the same shape as the CSV one."""
    assert snap_compare(
        ViewerApp(str(sample_parquet)),
        terminal_size=TERMINAL_SIZE,
    )