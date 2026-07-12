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
from textual.widgets import DataTable, Input, Label

from angoor.app import ViewerApp

ROWS, COLS = 5, 5
# Column 0 is the headerless index column; data columns live at 1..COLS.
DATA_COLS = COLS + 1


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
        # +1 for the leading headerless index column.
        assert len(table.columns) == DATA_COLS
        # Column 0 is the index; column 2 is the first real data column ("name").
        assert table.get_cell_at(Coordinate(0, 2)) == "Widget Alpha"


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
        # Last column is the final data column (index col + COLS data cols - 1).
        assert table.cursor_coordinate.column == DATA_COLS - 1


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


async def test_yw_copies_current_cell(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "w")
        await pilot.pause()
        clipboard.assert_called_once_with("1")


async def test_yw_copies_cell_after_navigation(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Column 2 is the "name" column (col 0 = index, col 1 = id).
        await pilot.press("l", "l")  # name
        await pilot.press("j")  # row 1
        await pilot.press("y", "w")
        await pilot.pause()
        clipboard.assert_called_once_with("Widget Beta")


async def test_yy_copies_row_comma_joined(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "y")
        await pilot.pause()
        clipboard.assert_called_once_with(",".join(("1", "Widget Alpha", "tools", "9.99", "True")))


async def test_yc_copies_column_newline_joined(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "c")
        await pilot.pause()
        # Cursor sits on the index column (col 0); indices == 1..5.
        clipboard.assert_called_once_with("1\n2\n3\n4\n5")


async def test_yw_on_empty_cell_copies_blank(sample_csv, clipboard):
    """Row 4, price column is None -> _fmt -> empty string."""
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "j", "j")  # row 4
        # col 0=index,1=id,2=name,3=category,4=price -> four `l`s.
        await pilot.press("l", "l", "l", "l")
        await pilot.pause()
        await pilot.press("y", "w")
        await pilot.pause()
        clipboard.assert_called_once_with("")


async def test_copy_emit_notifications(sample_csv, clipboard, notifications):
    """Each copy chord fires a notify() with the right verb."""
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y", "y")
        await pilot.press("y", "w")
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
        # "Widget Alpha" contains "wid"; it lives in the "name" column (col 2).
        await pilot.press("/", "w", "i", "d")
        await pilot.pause()
        assert _bar(app).value == "wid"
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 2)
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
        # Column 3 is "category" (0=index,1=id,2=name,3=category).
        await pilot.press("l", "l", "l")  # col 3
        await pilot.press("j", "j")  # row 2 (Gadget Gamma, electronics)
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(2, 3)
        # // -> col search (bar hidden until the user types).
        await pilot.press("/", "/")
        await pilot.pause()
        assert app._search_mode == "col"
        assert _bar(app).has_class("hidden")
        # search "electronics" -> first match below row 2 is row 3.
        await pilot.press("e", "l", "e", "c", "t", "r", "o", "n", "i", "c", "s")
        await pilot.pause()
        assert not _bar(app).has_class("hidden")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(3, 3)
        assert app._last_search == ("col", "electronics")


async def test_n_repeats_last_search(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        # col 3 = category, values: tools, tools, electronics, electronics, misc.
        await pilot.press("l", "l", "l")  # col 3, row 0
        await pilot.pause()
        # // then "tools" -> search starts at row+1, so first match is row 1.
        await pilot.press("/", "/")
        await pilot.press("t", "o", "o", "l", "s")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 3)
        # n -> next match wraps to row 0.
        await pilot.press("n")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 3)
        # n again -> back to row 1.
        await pilot.press("n")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(1, 3)


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
        # Col search is active but the bar stays hidden until something is typed.
        assert app._serach_active()
        assert bar.has_class("hidden")
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
        # Land on the last column (col 5 = "active"). Search "widget" -> only in
        # the "name" column (col 2), which is behind us, so it must wrap.
        await pilot.press("l", "l", "l", "l", "l")  # col 5
        await pilot.pause()
        await pilot.press("/", "w", "i", "d", "g", "e", "t")
        await pilot.press("enter")
        await pilot.pause()
        assert table.cursor_coordinate == Coordinate(0, 2)


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


# ----------------------------------------------------------------- index column


async def test_index_column_is_first_without_header(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = _table(app)
        first = next(iter(table.columns.values()))
        assert first.label.plain == ""
        assert table.get_cell_at(Coordinate(0, 0)) == "1"
        assert table.get_cell_at(Coordinate(4, 0)) == "5"


async def test_value_at_maps_index_and_data(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._value_at(0, 0) == 1
        assert app._value_at(0, 1) == 1  # id
        assert app._value_at(0, 2) == "Widget Alpha"  # name


# ----------------------------------------------------------------- minification


def test_fmt_display_minifies_long_text():
    from angoor.app import ViewerApp

    long = "Very long text keeps going for a very long time it ends"
    out = ViewerApp._fmt_display(long)
    assert "…" in out
    assert out.startswith("Very")
    assert out.endswith("ends")
    assert len(out) <= 40


def test_fmt_display_leaves_short_text():
    from angoor.app import ViewerApp

    assert ViewerApp._fmt_display("Widget Alpha") == "Widget Alpha"
    assert ViewerApp._fmt_display(None) == ""


# ----------------------------------------------------------------- view popup


async def test_v_opens_cell_viewer(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Move to the "name" column (col 2) row 0.
        await pilot.press("l", "l")
        await pilot.press("v")
        await pilot.pause()
        screens = app.screen_stack
        assert any(s.__class__.__name__ == "CellViewerScreen" for s in screens)
        await pilot.press("escape")
        await pilot.pause()
        assert not any(s.__class__.__name__ == "CellViewerScreen" for s in app.screen_stack)


# ----------------------------------------------------------------- footer / help


async def test_footer_shows_help_initially(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one("#footer", Label)
        assert "hjkl" in str(footer._Static__content)


async def test_footer_shows_search_mode(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "/")
        await pilot.pause()
        footer = app.query_one("#footer", Label)
        assert "COL SEARCH" in str(footer._Static__content)
        await pilot.press("escape")
        await pilot.pause()
        assert "hjkl" in str(app.query_one("#footer", Label)._Static__content)


# ----------------------------------------------------------------- search reveal


async def test_col_search_bar_hidden_until_typed(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        bar = _bar(app)
        await pilot.press("l", "l", "l")  # category column
        await pilot.press("/", "/")
        await pilot.pause()
        assert app._search_mode == "col"
        assert bar.has_class("hidden")
        # The first printable char materialises the bar with that char inside.
        await pilot.press("e")
        await pilot.pause()
        assert not bar.has_class("hidden")
        assert bar.value == "e"


# ----------------------------------------------------------------- header mode


async def test_gh_enters_header_preserving_column(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("l", "l", "l", "j", "j")  # row 2, col 3
        await pilot.pause()
        await pilot.press("g", "h")
        await pilot.pause()
        assert app._in_header is True
        # Cursor parks on row 0, column preserved.
        assert table.cursor_coordinate == Coordinate(0, 3)


async def test_gg_goes_to_first_row_not_header(sample_csv):
    """TODO guarantee: gg still goes to the first row (does NOT enter header)."""
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("j", "j", "l", "l")
        await pilot.pause()
        await pilot.press("g", "g")
        await pilot.pause()
        assert app._in_header is False
        assert table.cursor_coordinate == Coordinate(0, 2)


async def test_gg_exits_header_to_first_row(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        assert app._in_header is True
        await pilot.press("g", "g")
        await pilot.pause()
        assert app._in_header is False
        assert table.cursor_coordinate.row == 0


async def test_j_exits_header(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        assert app._in_header is False
        # Header sits above row 0; one `j` lands on the first data row.
        assert table.cursor_coordinate.row == 0


async def test_k_in_header_is_noop(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        row_before = table.cursor_coordinate.row
        await pilot.press("k", "k")
        await pilot.pause()
        assert app._in_header is True
        assert table.cursor_coordinate.row == row_before


async def test_G_exits_header_to_last_row(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        await pilot.press("G")
        await pilot.pause()
        assert app._in_header is False
        assert table.cursor_coordinate.row == ROWS - 1


async def test_h_l_move_header_column(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        await pilot.press("l", "l")
        await pilot.pause()
        assert app._in_header is True
        assert table.cursor_coordinate.column == 2


async def test_circumflex_dollar_work_in_header(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        await pilot.press("$")
        await pilot.pause()
        assert table.cursor_coordinate.column == DATA_COLS - 1
        await pilot.press("^")
        await pilot.pause()
        assert table.cursor_coordinate.column == 0
        assert app._in_header is True


async def test_yw_in_header_copies_column_name(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.press("l", "l")  # col 2 -> header "name"
        await pilot.press("y", "w")
        await pilot.pause()
        clipboard.assert_called_once_with("name")


async def test_yw_in_header_index_column_copies_blank(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.pause()
        await pilot.press("y", "w")
        await pilot.pause()
        clipboard.assert_called_once_with("")


async def test_yy_in_header_copies_header_names(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.press("y", "y")
        await pilot.pause()
        clipboard.assert_called_once_with("id,name,category,price,active")


async def test_yc_in_header_still_copies_column_values(sample_csv, clipboard):
    """ "rest of the behaviour remains the same": yc copies the column values."""
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.press("l", "l")  # name column
        await pilot.press("y", "c")
        await pilot.pause()
        names = ["Widget Alpha", "Widget Beta", "Gadget Gamma", "Gadget Delta", "Doohickey Epsilon"]
        clipboard.assert_called_once_with("\n".join(names))


async def test_v_in_header_views_header_name(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.press("l", "l")  # "name"
        await pilot.press("v")
        await pilot.pause()
        screens = app.screen_stack
        assert any(s.__class__.__name__ == "CellViewerScreen" for s in screens)
        viewer = next(s for s in screens if s.__class__.__name__ == "CellViewerScreen")
        assert viewer.text == "name"
        await pilot.press("escape")
        await pilot.pause()
        assert not any(s.__class__.__name__ == "CellViewerScreen" for s in app.screen_stack)


async def test_row_search_in_header_searches_header_names(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("g", "h")
        await pilot.pause()
        # /name -> header "name" lives at col 2.
        await pilot.press("/", "n", "a", "m", "e")
        await pilot.pause()
        assert _bar(app).value == "name"
        await pilot.press("enter")
        await pilot.pause()
        assert app._in_header is True
        assert table.cursor_coordinate == Coordinate(0, 2)
        assert app._last_search == ("row", "name")


async def test_yw_in_header_then_j_returns_to_data(sample_csv, clipboard):
    app = make_app(sample_csv, clipboard)
    async with app.run_test() as pilot:
        await pilot.press("g", "h", "l", "l")  # header "name"
        await pilot.press("y", "w")
        await pilot.pause()
        assert clipboard.call_args_list[-1].args[0] == "name"
        await pilot.press("j")
        await pilot.pause()
        assert app._in_header is False
        # Back in data at row 0, col 2 -> "Widget Alpha".
        await pilot.press("y", "w")
        await pilot.pause()
        assert clipboard.call_args_list[-1].args[0] == "Widget Alpha"


async def test_footer_shows_header_mode(sample_csv):
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        await pilot.press("g", "h")
        await pilot.pause()
        footer = app.query_one("#footer", Label)
        assert "HEADER" in str(footer._Static__content)
        await pilot.press("j")
        await pilot.pause()
        assert "hjkl" in str(app.query_one("#footer", Label)._Static__content)


async def test_malformed_g_then_h_is_not_header(sample_csv):
    """`gh` is the only header entry; a non-g then h must just move left."""
    app = make_app(sample_csv)
    async with app.run_test() as pilot:
        table = _table(app)
        await pilot.press("l", "l")
        await pilot.pause()
        col_before = table.cursor_coordinate.column
        await pilot.press("h")
        await pilot.pause()
        assert app._in_header is False
        assert table.cursor_coordinate.column == col_before - 1
