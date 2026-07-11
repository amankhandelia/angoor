"""Interaction-based regression tests for the ViewerApp Textual TUI.

These drive the app headlessly via the Pilot object, simulating real key
presses, and assert on widget state / cursor coordinates / clipboard calls
so that VIM keybinding regressions are caught before they ship.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

from angoor.app import ViewerApp

ROWS, COLS = 5, 5


def make_app(csv_path: Path, clipboard: MagicMock | None = None) -> ViewerApp:
    app = ViewerApp(str(csv_path))
    if clipboard is not None:
        app.copy_to_clipboard = clipboard  # type: ignore[method-assign]
    return app


def _table(app: ViewerApp) -> DataTable:
    return app.query_one("#table", DataTable)


def _bar(app: ViewerApp) -> Input:
    return app.query_one("#search-bar", Input)


# ----------------------------------------------------------------- mount / state


async def test_app_loads_table_before_screen_session(sample_csv):
    """Constructor materializes the table eagerly (guarantee from AGENTS.md)."""
    app = ViewerApp(str(sample_csv))
    assert app.columns == ["id", "name", "category", "price", "active"]
    assert len(app.rows) == ROWS

    async with app.run_test() as pilot:
        await pilot.pause()
        table = _table(app)
        assert table.row_count == ROWS
        assert len(table.columns) == COLS
        assert table.get_cell_at(Coordinate(0, 1)) == "Widget Alpha"


async def test_initial_cursor_at_first_data_cell(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _table(app).cursor_coordinate == Coordinate(0, 0)


async def test_search_bar_is_hidden_until_invoked(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = _bar(app)
        assert bar.has_class("hidden")
        assert app._search_mode is None


# ----------------------------------------------------------------- navigation


async def test_hjkl_moves_cursor(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = _table(app)

        await pilot.press("j")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 0)

        await pilot.press("l")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 1)

        await pilot.press("k")
        await pilot.press("h")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 0)


async def test_j_clamps_at_last_row(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        for _ in range(ROWS + 5):
            await pilot.press("j")
        await pilot.pause()
        assert table.cursor_coordinate.row == ROWS - 1


async def test_h_clamps_at_first_col(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        for _ in range(COLS + 5):
            await pilot.press("h")
        await pilot.pause()
        assert table.cursor_coordinate.column == 0


async def test_gg_goes_to_first_row_preserving_column(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("l", "l", "j", "j")
        await pilot.pause()
        await pilot.press("g", "g")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 2)


async def test_capital_G_goes_to_last_row_preserving_column(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("G")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(ROWS - 1, 1)


async def test_dollar_goes_to_row_end(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("$")
        await pilot.pause()
        assert table.cursor_coordinate.column == COLS - 1


async def test_circumflex_goes_to_row_start(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("l", "l", "l")
        await pilot.pause()
        await pilot.press("^")
        await pilot.pause()
        assert table.cursor_coordinate.column == 0


# ----------------------------------------------------------------- pending chord


async def test_malformed_g_chord_is_silently_dropped(sample_csv):
    """`gq` -> pending='g' then 'q' falls into the g branch and is swallowed (q does NOT quit)."""
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g", "q")
        await pilot.pause()
        # The app is still alive (q was swallowed, not quit).
        assert app._pending is None
        assert app.is_running


async def test_g_pending_is_consumed_by_first_g(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # Move down first, then `gg` should bring us back.
        await pilot.press("j", "j")
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        # pending is now 'g'. Pressing an unrelated key clears it without moving.
        assert app._pending == "g"
        await pilot.press("x")
        await pilot.pause()
        assert app._pending is None
        # Cursor unchanged by the malformed chord.
        assert table.cursor_coordinate == Coordinate(2, 0)


# ----------------------------------------------------------------- copy


async def test_ye_copies_current_cell(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "e")
        await pilot.pause()
        clipboard.assert_called_once_with("1")


async def test_ye_copies_cell_after_navigation(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("l")  # column 1 -> name
        await pilot.press("j")  # row 1
        await pilot.press("y", "e")
        await pilot.pause()
        clipboard.assert_called_once_with("Widget Beta")


async def test_yy_copies_row_tab_joined(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "y")
        await pilot.pause()
        clipboard.assert_called_once_with("\t".join(("1", "Widget Alpha", "tools", "9.99", "True")))


async def test_yc_copies_column_newline_joined(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "c")
        await pilot.pause()
        clipboard.assert_called_once_with("1\n2\n3\n4\n5")


async def test_ye_on_empty_cell_copies_blank(sample_csv, clipboard):
    """Row 4, price column is None -> _fmt -> empty string."""
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "j", "j")  # row 4
        await pilot.press("l", "l", "l")  # column 3 -> price
        await pilot.pause()
        await pilot.press("y", "e")
        await pilot.pause()
        clipboard.assert_called_once_with("")


async def test_copy_emit_notifications(sample_csv, clipboard, notifications):
    """Each copy chord fires a notify() with the right verb."""
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "y")
        await pilot.press("y", "e")
        await pilot.press("y", "c")
        await pilot.pause()
    messages = [n["message"] for n in notifications]
    assert messages == ["copied row", "copied cell", "copied column"]


# ----------------------------------------------------------------- search


async def test_row_search_moves_to_matching_cell(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # /wid -> search "wid" inside the current row (row 0).
        # "Widget Alpha" contains "wid".
        await pilot.press("/", "w", "i", "d")
        await pilot.pause()
        assert _bar(app).value == "wid"
        await pilot.press("enter")
        await pilot.pause()
        # matched in column 1 ("name") of row 0.
        assert table.cursor_coordinate == Coordinate(0, 1)
        assert app._last_search == ("row", "wid")


async def test_row_search_seed_is_not_overwritten(sample_csv):
    """Regression guard: the first typed char must APPEND to the seed, not replace it.

    This catches the select-on-focus bug where `/foo` would search "oo" not "foo".
    """
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.press("/", "w", "i", "d")
        await pilot.pause()
        assert _bar(app).value == "wid"


async def test_col_search_via_double_slash(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # Move to column 2 ("category") where "electronics" appears in rows 2,3.
        await pilot.press("l", "l")  # col 2
        await pilot.press("j", "j")  # row 2 (Gadget Gamma, electronics)
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(2, 2)
        # // -> col search (empty seed)
        await pilot.press("/", "/")
        await pilot.pause()
        assert app._search_mode == "col"
        assert _bar(app).value == ""
        # search "electronics" -> first match below row 2 is row 3.
        await pilot.press("e", "l", "e", "c", "t", "r", "o", "n", "i", "c", "s")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(3, 2)
        assert app._last_search == ("col", "electronics")


async def test_n_repeats_last_search(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # col 2 = category, values: tools, tools, electronics, electronics, misc.
        await pilot.press("l", "l")  # col 2, row 0
        await pilot.pause()
        # // then "tools" -> search starts at row+1, so first match is row 1.
        await pilot.press("/", "/")
        await pilot.press("t", "o", "o", "l", "s")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 2)
        # n -> next match wraps to row 0.
        await pilot.press("n")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 2)
        # n again -> back to row 1.
        await pilot.press("n")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 2)


async def test_search_no_match_warns(sample_csv, notifications):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.press("/", "z", "z", "z")
        await pilot.press("enter")
        await pilot.pause()
        warns = [n for n in notifications if n.get("severity") == "warning"]
        assert warns and "no match" in warns[-1]["message"].lower()


async def test_escape_closes_search(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        bar = _bar(app)
        await pilot.press("/", "/")
        await pilot.pause()
        assert app._serach_active()
        assert not bar.has_class("hidden")
        await pilot.press("escape")
        await pilot.pause()
        assert not app._serach_active()
        assert bar.has_class("hidden")
        assert bar.value == ""


async def test_search_wraps_around(sample_csv):
    """A row search that finds nothing ahead should wrap to start of row."""
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # Start at col 4 (last col, "active"). Search "widget" -> only in col 1,
        # which is behind us, so it must wrap to col 1.
        await pilot.press("l", "l", "l", "l")  # col 4
        await pilot.pause()
        await pilot.press("/", "w", "i", "d", "g", "e", "t")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 1)


# ----------------------------------------------------------------- quit


async def test_q_quits_app(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert not app.is_running


async def test_ctrl_c_quits_app(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
    assert not app.is_running