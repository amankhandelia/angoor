"""VIM-keybindings tabular data viewer built with Textual."""

from __future__ import annotations

import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, TextArea

from .backend import load_table

_MAX_CELL_WIDTH = 40
_HELP = (
    "hjkl move  gg top  gh header  G last  ^/$ ends  "
    "yw cell  yc col  yy row  / row  // col  "
    "n next  v view  q quit"
)
_HEADER_HELP = "HEADER  ·  yw copy name  ·  j back to rows"


class CellViewerScreen(ModalScreen):
    """A modal that shows the full, unminified contents of a single cell."""

    CSS = """
    CellViewerScreen {
        align: center middle;
    }
    #cell-viewer {
        width: 70%;
        height: 60%;
        border: round $accent;
        padding: 0 1;
    }
    #cell-viewer Label {
        height: 1;
        color: $text-muted;
    }
    #cell-viewer TextArea {
        border: none;
    }
    """

    BINDINGS = [Binding("escape", "dismiss", "close", show=False)]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(id="cell-viewer"):
            yield Label("cell viewer  ·  Esc to close")
            yield TextArea(self.text or "", read_only=True, soft_wrap=True, show_cursor=False)


class ViewerApp(App):
    """A VIM-flavoured viewer for CSV / Parquet tables."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #table {
        height: 1fr;
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
    #footer {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
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
        # When True the cursor logically sits on the header row (the column
        # names); the DataTable itself can't host a cursor on its header, so
        # we keep it parked on row 0 and translate reads via this flag.
        self._in_header: bool = False

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        yield DataTable(id="table", cursor_type="cell", zebra_stripes=True)
        yield Input(
            id="search-bar", placeholder="search…", classes="hidden", select_on_focus=False
        )
        yield Label(_HELP, id="footer")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        # Lead with a headerless index column (row numbers, 1-based).
        table.add_column("", key="__index__")
        for name in self.columns:
            table.add_column(str(name))
        for i, row in enumerate(self.rows, start=1):
            table.add_row(str(i), *[self._fmt_display(v) for v in row])
        # Place the cursor at the top-left cell.
        if self.rows:
            table.move_cursor(row=0, column=0)
        self.sub_title = self.path

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _fmt(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _minify(text: str) -> str:
        """Apple-style middle truncation for long cells (start…end)."""
        if len(text) <= _MAX_CELL_WIDTH:
            return text
        keep = _MAX_CELL_WIDTH - 1
        head = keep // 2
        tail = keep - head
        return f"{text[:head]}…{text[-tail:]}"

    @classmethod
    def _fmt_display(cls, value: object) -> str:
        return cls._minify(cls._fmt(value))

    def _value_at(self, row: int, col: int) -> object:
        """Return the raw value shown at a DataTable coordinate.

        Column 0 is the headerless index column; columns 1.. map to self.rows.
        """
        if col == 0:
            return row + 1
        return self.rows[row][col - 1]

    def _header_name(self, col: int) -> str:
        """Return the header label for a DataTable column index.

        Column 0 is the headerless index column (empty label); columns 1..
        map to ``self.columns``.
        """
        if col == 0:
            return ""
        return self._fmt(self.columns[col - 1])

    def _table(self) -> DataTable:
        return self.query_one("#table", DataTable)

    def _bar(self) -> Input:
        return self.query_one("#search-bar", Input)

    def _footer(self) -> Label:
        return self.query_one("#footer", Label)

    def _update_footer(self) -> None:
        if self._search_mode == "row":
            self._footer().update("ROW SEARCH  ·  type query  ·  Enter submit  ·  Esc cancel")
        elif self._search_mode == "col":
            self._footer().update("COL SEARCH  ·  type query  ·  Enter submit  ·  Esc cancel")
        elif self._in_header:
            self._footer().update(_HEADER_HELP)
        else:
            self._footer().update(_HELP)

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

    def _go_to_first_row(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=0, column=table.cursor_coordinate.column)

    def _enter_header(self) -> None:
        # Park the cursor on row 0 (the DataTable can't hold a cursor on the
        # header) and translate reads via _in_header.
        table = self._table()
        if table.row_count:
            table.move_cursor(row=0, column=table.cursor_coordinate.column)
        self._in_header = True
        self._update_footer()

    def _exit_header(self) -> None:
        if not self._in_header:
            return
        self._in_header = False
        self._update_footer()

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
        if not self.rows and not self._in_header:
            return
        r, c = table.cursor_coordinate
        if self._in_header:
            text = self._header_name(c)
        else:
            text = self._fmt(self._value_at(r, c))
        self.copy_to_clipboard(text)
        self.notify("copied cell")

    def _copy_row(self) -> None:
        if not self.rows and not self._in_header:
            return
        if self._in_header:
            text = ",".join(str(name) for name in self.columns)
        else:
            r = self._table().cursor_coordinate.row
            text = ",".join(self._fmt(v) for v in self.rows[r])
        self.copy_to_clipboard(text)
        self.notify("copied row")

    def _copy_col(self) -> None:
        table = self._table()
        if not self.rows:
            return
        c = table.cursor_coordinate.column
        text = "\n".join(self._fmt(self._value_at(rr, c)) for rr in range(len(self.rows)))
        self.copy_to_clipboard(text)
        self.notify("copied column")

    # ---------------------------------------------------------------- view

    def _view_cell(self) -> None:
        table = self._table()
        if not self.rows and not self._in_header:
            return
        r, c = table.cursor_coordinate
        if self._in_header:
            text = self._header_name(c)
        else:
            text = self._fmt(self._value_at(r, c))
        self.push_screen(CellViewerScreen(text))

    # ---------------------------------------------------------------- search

    def _start_search(self, mode: str, initial: str = "") -> None:
        self._search_mode = mode
        bar = self._bar()
        bar.placeholder = "row search…" if mode == "row" else "col search…"
        self._update_footer()
        # The bar only materialises once the user has typed something; with a
        # seed the first char already counts, so reveal immediately.
        if initial:
            self._reveal_search(initial)

    def _reveal_search(self, seed: str) -> None:
        bar = self._bar()
        bar.remove_class("hidden")
        bar.value = seed
        bar.focus()
        bar.cursor_position = len(seed)

    def _close_search(self) -> None:
        bar = self._bar()
        bar.add_class("hidden")
        bar.value = ""
        self._search_mode = None
        self._update_footer()
        self._table().focus()

    def _do_search(self, mode: str, query: str) -> None:
        if not query or not self.rows:
            return
        table = self._table()
        coord = table.cursor_coordinate
        needle = query.lower()
        n_cols = len(table.columns)
        if mode == "row":
            r = coord.row
            if self._in_header:
                cells = [self._header_name(cc).lower() for cc in range(n_cols)]
            else:
                cells = [self._fmt(self._value_at(r, cc)).lower() for cc in range(n_cols)]
            search_order = list(range(coord.column + 1, n_cols)) + list(
                range(0, coord.column + 1)
            )
            for c in search_order:
                if needle in cells[c]:
                    table.move_cursor(row=r, column=c)
                    return
        elif mode == "col":
            c = coord.column
            col_vals = [
                self._fmt(self._value_at(rr, c)).lower() for rr in range(len(self.rows))
            ]
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
        # Search mode: the bar appears only once a printable char is typed.
        if self._search_mode is not None:
            bar = self._bar()
            if bar.has_class("hidden"):
                if event.key == "escape":
                    event.prevent_default()
                    self._close_search()
                    return
                ch = event.character
                if ch is not None:
                    event.prevent_default()
                    self._reveal_search(ch)
                return
            # Bar is visible & focused — let the Input handle the keys.
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
            if self._in_header:
                self._exit_header()
                return
            self._move(1, 0)
        elif key == "k":
            event.prevent_default()
            if self._in_header:
                return
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
            self._exit_header()
            self._go_to_last_row()
        elif key == "^":
            event.prevent_default()
            self._go_to_row_start()
        elif key == "$":
            event.prevent_default()
            self._go_to_row_end()
        elif key == "v":
            event.prevent_default()
            self._view_cell()
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
                self._exit_header()
                self._go_to_first_row()
            elif key == "h":
                self._enter_header()
            # else: malformed "g<x>" — just drop silently (vim-style).
        elif prev == "y":
            if key == "w":
                self._copy_cell()
            elif key == "c":
                self._copy_col()
            elif key == "y":
                self._copy_row()
        elif prev == "/":
            if key == "/":
                # // → search within the active column (bar hidden until typed).
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