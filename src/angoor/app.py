"""VIM-keybindings tabular data viewer built with Textual."""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input

from .backend import load_table


class ViewerApp(App):
    """A VIM-flavoured viewer for CSV / Parquet tables."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #search-bar {
        dock: bottom;
        height: 3;
        border: round $accent;
        padding: 0 1;
    }
    #search-bar.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_search", "cancel search", show=False),
        Binding("ctrl+c", "quit", "quit", show=True),
    ]

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        # Load eagerly (before the screen session starts) so that errors are
        # surfaced as clean stderr messages instead of in-TUI tracebacks.
        self.columns, self.rows = load_table(path)
        # Multi-key command state machine.
        self._pending: str | None = None
        # Active search mode: "row" or "col" (None when not searching).
        self._search_mode: str | None = None
        # Last search info so the user can repeat with "n".
        self._last_search: tuple[str | None, str] = (None, "")

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        yield DataTable(id="table", cursor_type="cell", zebra_stripes=True)
        yield Input(id="search-bar", placeholder="search…", classes="hidden")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns(*[str(c) for c in self.columns])
        for row in self.rows:
            table.add_row(*[self._fmt(v) for v in row])
        # Place the cursor at the first data cell.
        if self.rows:
            table.move_cursor(row=0, column=0)
        self.sub_title = self.path

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _fmt(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    def _table(self) -> DataTable:
        return self.query_one("#table", DataTable)

    def _clamp_coord(self, row: int, col: int) -> Coordinate:
        table = self._table()
        n_rows = table.row_count
        n_cols = len(table.columns)
        if n_rows == 0:
            r = 0
        else:
            r = min(max(0, row), n_rows - 1)
        c = min(max(0, col), n_cols - 1)
        return Coordinate(r, c)

    def _serach_active(self) -> bool:
        return self._search_mode is not None

    # -------------------------------------------------------------- navigation

    def _move(self, drow: int, dcol: int) -> None:
        table = self._table()
        coord = table.cursor_coordinate
        target = self._clamp_coord(coord.row + drow, coord.column + dcol)
        table.move_cursor(row=target.row, column=target.column)

    def _go_to_header(self) -> None:
        table = self._table()
        # "header" in our viewer == the top-most data row (row 0).
        if table.row_count:
            table.move_cursor(row=0, column=table.cursor_coordinate.column)

    def _go_to_last_row(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(
                row=table.row_count - 1, column=table.cursor_coordinate.column
            )

    def _go_to_row_start(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=table.cursor_coordinate.row, column=0)

    def _go_to_row_end(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(
                row=table.cursor_coordinate.row, column=len(table.columns) - 1
            )

    # ---------------------------------------------------------------- copy

    def _copy_cell(self) -> None:
        table = self._table()
        if not self.rows:
            return
        r, c = table.cursor_coordinate
        self.copy_to_clipboard(self._fmt(self.rows[r][c]))
        self.notify("copied cell")

    def _copy_row(self) -> None:
        if not self.rows:
            return
        r = self._table().cursor_coordinate.row
        text = "\t".join(self._fmt(v) for v in self.rows[r])
        self.copy_to_clipboard(text)
        self.notify("copied row")

    def _copy_col(self) -> None:
        if not self.rows:
            return
        c = self._table().cursor_coordinate.column
        text = "\n".join(self._fmt(row[c]) for row in self.rows)
        self.copy_to_clipboard(text)
        self.notify("copied column")

    # ---------------------------------------------------------------- search

    def _start_search(self, mode: str, initial: str = "") -> None:
        self._search_mode = mode
        bar: Input = self.query_one("#search-bar", Input)
        bar.remove_class("hidden")
        bar.value = initial
        bar.focus()
        # Put the cursor at the end of any initial text.
        bar.cursor_position = len(initial)

    def _close_search(self) -> None:
        bar: Input = self.query_one("#search-bar", Input)
        bar.add_class("hidden")
        bar.value = ""
        self._search_mode = None
        self._table().focus()

    def _do_search(self, mode: str, query: str) -> None:
        if not query or not self.rows:
            return
        table = self._table()
        coord = table.cursor_coordinate
        needle = query.lower()
        if mode == "row":
            r = coord.row
            cells = [self._fmt(v).lower() for v in self.rows[r]]
            search_order = list(range(coord.column + 1, len(cells))) + list(
                range(0, coord.column + 1)
            )
            for c in search_order:
                if needle in cells[c]:
                    table.move_cursor(row=r, column=c)
                    return
        elif mode == "col":
            c = coord.column
            col_vals = [self._fmt(row[c]).lower() for row in self.rows]
            search_order = list(range(coord.row + 1, len(col_vals))) + list(
                range(0, coord.row + 1)
            )
            for r in search_order:
                if needle in col_vals[r]:
                    table.move_cursor(row=r, column=c)
                    return
        self.notify(f"no match for {query!r}", severity="warning")

    # -------------------------------------------------------------- event hooks

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-bar":
            return
        mode = self._search_mode
        query = event.value
        self._last_search = (mode, query)
        self._close_search()
        if mode is not None:
            self._do_search(mode, query)

    # -------------------------------------------------------------- key handling

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        # While the search bar is focused, let the Input handle the keys.
        if self._serach_active():
            return

        # Textual exposes punctuation keys (like `/`) by symbolic names
        # ("slash"), so prefer the printable character when available.
        glyph = event.character or event.key

        if self._pending is None:
            self._handle_single(event, glyph)
        else:
            prev = self._pending
            self._pending = None
            self._handle_followup(prev, glyph)

    def _handle_single(self, event, key: str) -> None:  # type: ignore[no-untyped-def]
        if key == "j":
            event.prevent_default()
            self._move(1, 0)
        elif key == "k":
            event.prevent_default()
            self._move(-1, 0)
        elif key == "h":
            event.prevent_default()
            self._move(0, -1)
        elif key == "l":
            event.prevent_default()
            self._move(0, 1)
        elif key == "g":
            event.prevent_default()
            self._pending = "g"
        elif key == "G":
            event.prevent_default()
            self._go_to_last_row()
        elif key == "^":
            event.prevent_default()
            self._go_to_row_start()
        elif key == "$":
            event.prevent_default()
            self._go_to_row_end()
        elif key == "q":
            event.prevent_default()
            self.exit()
        elif key == "y":
            event.prevent_default()
            self._pending = "y"
        elif key == "/":
            event.prevent_default()
            self._pending = "/"
        elif key == "n":
            event.prevent_default()
            mode, query = self._last_search
            if mode is not None:
                self._do_search(mode, query)

    def _handle_followup(self, prev: str, key: str) -> None:  # type: ignore[no-untyped-def]
        if prev == "g":
            if key == "g":
                self._go_to_header()
            # else: malformed "g<x>" — just drop silently (vim-style).
        elif prev == "y":
            if key == "e":
                self._copy_cell()
            elif key == "c":
                self._copy_col()
            elif key == "y":
                self._copy_row()
        elif prev == "/":
            if key == "/":
                # // → search within the active column.
                self._start_search("col")
            else:
                # / followed by any other key → row search seeded with that key.
                self._start_search("row", initial=key)

    # -------------------------------------------------------------- actions

    def action_cancel_search(self) -> None:
        if self._serach_active():
            self._close_search()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: angoor <file.csv|file.parquet>", file=sys.stderr)
        sys.exit(2)
    try:
        app = ViewerApp(sys.argv[1])
    except (FileNotFoundError, ValueError) as exc:
        print(f"angoor: {exc}", file=sys.stderr)
        sys.exit(1)
    app.run()