"""VIM-keybindings tabular data viewer built with Textual."""

from __future__ import annotations

import sys

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, TextArea

from .backend import load_table

_MAX_CELL_WIDTH = 40
_CELL_HINTS = [
    ("hjkl", "move"),
    ("gg", "top"),
    ("gh", "header"),
    ("G", "last"),
    ("^/$", "ends"),
    ("v", "view"),
    ("/", "row search"),
    ("//", "col search"),
    ("n", "next"),
    ("q", "quit"),
]
_HEADER_HINTS = [
    ("yw", "copy name"),
    ("yy", "copy names"),
    ("v", "view name"),
    ("h/l", "move"),
    ("j", "back"),
    ("esc", "exit header"),
]
_SEARCH_HINTS = [("enter", "submit"), ("esc", "cancel")]
_VIEWER_HINTS = [("j/k", "scroll"), ("yw", "copy"), ("esc", "close")]


def _render_hints(hints: list[tuple[str, str]]) -> Text:
    """Render a list of (key, description) pairs as a lazygit-style option bar.

    The keys are bolded and coloured; each pair is rendered as ``key: description``
    and pairs are separated by a dim ``|``.
    """
    sep = Text(" | ", style="dim")
    parts: list[Text] = []
    for key, desc in hints:
        parts.append(Text.assemble((f"{key} ", "bold cyan"), (desc, "")))
    out = Text()
    for i, p in enumerate(parts):
        if i:
            out.append(sep)
        out.append(p)
    return out


def _help_text() -> Text:
    return _render_hints(_CELL_HINTS)


def _header_help_text() -> Text:
    return _render_hints(_HEADER_HINTS)


def _search_help_text(mode: str) -> Text:
    label = "ROW SEARCH" if mode == "row" else "COL SEARCH"
    return Text.assemble((f"{label}  ·  ", "bold"), _render_hints(_SEARCH_HINTS))


def _viewer_help_text() -> Text:
    return Text.assemble(("CELL VIEWER  ·  ", "bold"), _render_hints(_VIEWER_HINTS))


class ViewerDataTable(DataTable):
    """DataTable that can visually highlight a header cell as the active cursor.

    Textual's DataTable cannot host a cursor on its header row, so ``ViewerApp``
    tracks "being in the header" as app-level state (``_in_header``). To make the
    highlight visually land on the header instead of row 0, this subclass overrides
    ``_should_highlight`` so that the header cell at the active column lights up
    whenever a header-active column has been set.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Active header column while in header mode, or None otherwise.
        self._header_active_column: int | None = None

    def set_header_active_column(self, column: int | None) -> None:
        """Set (or clear) the header column to render with the cursor highlight."""
        if column == self._header_active_column:
            return
        self._header_active_column = column
        # Bump _update_count so DataTable's line/cell render caches (keyed on
        # _update_count) are invalidated — otherwise re-rendering the header
        # reuses the stale (non-highlighted) cached cell renderables.
        self._update_count += 1
        self.refresh()

    def _should_highlight(self, cursor: Coordinate, target_cell: Coordinate, type_of_cursor: str) -> bool:  # type: ignore[override]
        if self._header_active_column is not None:
            # In header mode: only the header cell at the active column lights up.
            # Data cells are suppressed so the parked-row-0 cursor doesn't also
            # paint a cursor on the first data row.
            return target_cell.row == -1 and target_cell.column == self._header_active_column
        return super()._should_highlight(cursor, target_cell, type_of_cursor)  # type: ignore[arg-type]


class CellViewerScreen(ModalScreen):
    """A modal that shows the full, unminified contents of a single cell.

    Supports ``j``/``k`` (and arrow keys) for scrolling the long text. The
    cursor of the underlying ``DataTable`` is frozen for the lifetime of this
    modal — ``j``/``k`` only scroll the viewer, so a subsequent copy always
    copies the cell that was actually opened, regardless of scrolling.
    """

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

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self._pending: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="cell-viewer"):
            yield Label("cell viewer  ·  j/k scroll  ·  yw copy  ·  Esc to close")
            yield TextArea(self.text or "", read_only=True, soft_wrap=True, show_cursor=False)

    def on_mount(self) -> None:
        app = self.app
        if isinstance(app, ViewerApp):
            app._set_footer(_viewer_help_text())

    def on_unmount(self) -> None:
        app = self.app
        if isinstance(app, ViewerApp):
            app._update_footer()

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        # OWN every key press while the modal is open so h/l/etc. never leak
        # through to the parent ViewerApp's on_key (which would move the
        # underlying DataTable's cursor — see TODO item 3).
        event.stop()
        event.prevent_default()

        # Escape arrives as character "\x1b"; check the canonical key name.
        if event.key == "escape":
            self.dismiss()
            return

        glyph = event.character or event.key

        if self._pending == "y":
            self._pending = None
            if glyph in {"w", "y", "c"}:
                self.action_copy_text()
            return

        if glyph == "y":
            self._pending = "y"
        elif glyph in ("j", "down"):
            self.action_scroll_down()
        elif glyph in ("k", "up"):
            self.action_scroll_up()

    def action_scroll_down(self) -> None:
        self.query_one(TextArea).scroll_relative(y=1, animate=False)

    def action_scroll_up(self) -> None:
        self.query_one(TextArea).scroll_relative(y=-1, animate=False)

    def action_copy_text(self) -> None:
        self.app.copy_to_clipboard(self.text)
        self.app.notify("copied cell")


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
        yield ViewerDataTable(id="table", cursor_type="cell", zebra_stripes=True)
        yield Input(id="search-bar", placeholder="search…", classes="hidden", select_on_focus=False)
        yield Label(_help_text(), id="footer")

    def on_mount(self) -> None:
        table = self._table()
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

    def _table(self) -> ViewerDataTable:
        return self.query_one("#table", ViewerDataTable)

    def _bar(self) -> Input:
        return self.query_one("#search-bar", Input)

    def _footer(self) -> Label:
        return self.query_one("#footer", Label)

    def _set_footer(self, text: Text | str) -> None:
        self._footer().update(text)

    def _update_footer(self) -> None:
        if self._search_mode is not None:
            self._set_footer(_search_help_text(self._search_mode))
        elif self._in_header:
            self._set_footer(_header_help_text())
        else:
            self._set_footer(_help_text())

    def _sync_header_highlight(self) -> None:
        """Mirror the active column onto the DataTable's header highlight."""
        self._table().set_header_active_column(self._table().cursor_coordinate.column if self._in_header else None)

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
        self._sync_header_highlight()

    def _go_to_first_row(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=0, column=table.cursor_coordinate.column)
        self._sync_header_highlight()

    def _enter_header(self) -> None:
        # Park the cursor on row 0 (the DataTable can't hold a cursor on the
        # header) and translate reads via _in_header. The header cell at the
        # current column is visually highlighted via ViewerDataTable.
        table = self._table()
        if table.row_count:
            table.move_cursor(row=0, column=table.cursor_coordinate.column)
        self._in_header = True
        self._sync_header_highlight()
        self._update_footer()

    def _exit_header(self) -> None:
        if not self._in_header:
            return
        self._in_header = False
        self._sync_header_highlight()
        self._update_footer()

    def _go_to_last_row(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=table.row_count - 1, column=table.cursor_coordinate.column)
        self._sync_header_highlight()

    def _go_to_row_start(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=table.cursor_coordinate.row, column=0)
        self._sync_header_highlight()

    def _go_to_row_end(self) -> None:
        table = self._table()
        if table.row_count:
            table.move_cursor(row=table.cursor_coordinate.row, column=len(table.columns) - 1)
        self._sync_header_highlight()

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
            search_order = list(range(coord.column + 1, n_cols)) + list(range(0, coord.column + 1))
            for c in search_order:
                if needle in cells[c]:
                    table.move_cursor(row=r, column=c)
                    self._sync_header_highlight()
                    return
        elif mode == "col":
            c = coord.column
            col_vals = [self._fmt(self._value_at(rr, c)).lower() for rr in range(len(self.rows))]
            search_order = list(range(coord.row + 1, len(col_vals))) + list(range(0, coord.row + 1))
            for r in search_order:
                if needle in col_vals[r]:
                    table.move_cursor(row=r, column=c)
                    self._sync_header_highlight()
                    return
        self.notify(f"no match for {query!r}", severity="warning")

    # -------------------------------------------------------------- event hooks

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-bar":
            return
        # Guard against the cell viewer modal being open: the bar lives on the
        # main screen and shouldn't run a search while a modal is intercepting
        # keys (otherwise a copy inside the viewer could mutate the cursor).
        if isinstance(self.screen, CellViewerScreen):
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
