# AGENTS.md

Guidance for AI coding agents working on the `angoor` codebase.

## Project

`angoor` is a VIM-keybindings tabular data viewer TUI for CSV and Parquet files.
Frontend: [Textual](https://textual.textualize.io/). Backend: [DuckDB](https://duckdb.org/).
Runs cross-platform via `uv`.

## Quick reference

```bash
# install/sync deps (creates .venv from uv.lock)
uv sync

# run the app
uv run angoor path/to/data.csv
uv run angoor path/to/data.parquet
uv run python -m angoor path/to/data.csv      # equivalent

# there is NO configured lint or typecheck command.
# tests live in tests/ (pytest + pytest-asyncio + pytest-textual-snapshot).
# run them with:  uv run python -m pytest
# also verify by importing + running the app against test-data/*.csv|parquet
```

Python: `>=3.12` (`.python-version` pins to `3.12`). Build backend: `hatchling` (src layout).

## Repo layout

```
pyproject.toml          # project metadata, deps, hatchling build, [project.scripts] angoor=angoor.app:main
uv.lock                 # lockfile
.python-version         # 3.12
README.md               # user-facing keymap + run commands
src/angoor/
  __init__.py           # __version__; re-exports ViewerApp, main
  __main__.py           # enables `python -m angoor`
  app.py                # ViewerApp (Textual) — keybindings, copy, search; main() CLI entry
  backend.py            # load_table() via DuckDB; UnsupportedFileError
test-data/              # gitignored local fixtures (0.parquet, carrier_lookup.csv)
docs/                   # empty placeholder
```

## Architecture

### backend.py
- `load_table(path: str | Path) -> tuple[list[str], list[tuple]]` — normalizes the path (`expanduser().resolve()`), checks existence, dispatches on suffix via `_READERS` (`{.csv,.tsv: read_csv_auto, .parquet,.pq: read_parquet}`), runs `SELECT * FROM <reader>(?)` with the path **bound as a parameter** (the reader fn name is from a hardcoded allowlist, so no injection), and **eagerly materializes ALL rows** via `result.fetchall()`. Returns `(column_names, rows)`. Closes the connection in `finally`.
- Raises `UnsupportedFileError(ValueError)` for unknown suffixes, `FileNotFoundError` for missing files.

### app.py — `ViewerApp(App)`
- `__init__(path)`: **loads the table eagerly, before `app.run()` starts the Textual screen session**. This is deliberate so that file errors surface as clean stderr messages in `main()`'s try/except, not as unreadable tracebacks inside the TUI alternate screen. Do NOT move loading into `on_mount()` without preserving this guarantee.
- `compose()`: yields `DataTable(id="table", cursor_type="cell", zebra_stripes=True)` + `Input(id="search-bar", classes="hidden")` + `Label(id="footer")` (lazygit-style help pinned at the bottom).
- `on_mount()`: populates the DataTable from `self.columns` / `self.rows` (already loaded in `__init__`). A **headerless index column** (`add_column("", key="__index__")`) is inserted first, so DataTable columns are `index, <data cols>`; a row's displayed values are `str(i), *_fmt_display(...)`. `self.columns`/`self.rows` stay data-only — translate DataTable col ↔ data col via `_value_at(r, c)` (col 0 → row number, else `self.rows[r][c-1]`).
- Keybindings are **NOT** Textual `BINDINGS` (except `escape`→`cancel_search` and `ctrl+c`→`quit`). Everything else is a manual state machine in `on_key` because of 2-key chords (`gg`, `yy`, `yc`, `//`).
- `self._pending: str | None` holds the first key of a pending 2-key chord (`g`, `y`, or `/`). Next key dispatches via `_handle_followup`.
- **`glyph = event.character or event.key`** — critical: Textual reports punctuation as symbolic names (`slash`, `dollar`, `circumflex`), so we must compare against the printable char, not `event.key`. Without this, `/ ^ $` would never match.
- **Display minification**: `_fmt_display(value)` = `_minify(_fmt(value))` — Apple-style middle truncation (`start…end`) at `_MAX_CELL_WIDTH` (40). Long cells are shortened for the table only; `v` opens a `CellViewerScreen` modal (`ModalScreen` with a read-only `TextArea`) showing the **full** raw value, dismissed with `Esc`.
- **Search is in-memory Python substring matching** over the displayed cells (`_value_at(r,c)`), NOT DuckDB SQL. DuckDB is only used at load time. `_do_search` is case-insensitive (`.lower()`), wraps around (cursor+1→end→start→cursor), and only moves to the first match; use `n` to repeat.
  - The search bar **only appears once the user types a printable char**. `/` then a non-`/` key → row search seeded with that key (bar revealed immediately with the seed). `//` → column search with the bar kept **hidden** until the first printable key; until then the `#footer` label shows "ROW SEARCH"/"COL SEARCH" instead of the help text. `Esc` (handled explicitly in `on_key` when the bar is still hidden) cancels.
- **Copy** reads via `_value_at` then `_fmt` (None→`""`), NOT from the widget:
  - `yw` cell, `yc` column (newline-joined), `yy` row (comma-joined). Index column (col 0) copies the row number.
  - Uses `self.copy_to_clipboard(...)` (OSC52) + `self.notify(...)`.

### Keymap (source of truth: README.md)
`h j k l` move · `gg` first row · `gh` header · `G` last row · `^` row start · `$` row end · `q` quit · `yw/yc/yy` copy cell/col/row · `v` view cell · `/` row search · `//` col search · `n` repeat search · `Esc` cancel search · `Ctrl+C` quit.

### Header mode (`gh`)
Textual's `DataTable` cannot host its cursor on the header row, so "being in the header" is app-level state: `self._in_header: bool`. While True the DataTable cursor stays parked on row 0 and reads are translated via `_header_name(col)` (col 0 → `""` the headerless index, else `self.columns[col-1]`).
- Entry: `gh` chord → `_enter_header()` (moves cursor to row 0, preserving column, sets flag, updates footer to `_HEADER_HELP`).
- `j` exits (`_exit_header`) and stays on row 0 (header is conceptually row −1). `k` is a no-op (can't go above header). `G`/`gg` exit + go to last/first row. `h`/`l`/`^`/`$` move the active column and KEEP header mode.
- `yw` copies the header name; `yy` copies all header names comma-joined; `v` opens the cell viewer with the header name; `yc` is unchanged (copies the column's data values — "rest of the behaviour remains the same"). Row search (`/`) searches across header names; col search (`//`) still searches the column's values.

## Conventions

- `from __future__ import annotations` in both source files; use `str | None`, `tuple[...]` style.
- Type hints on public functions/helpers; `# type: ignore[no-untyped-def]` pragmas on Textual event handlers where `event` is untyped (`on_key`, `_handle_single`, `_handle_followup`).
- One-line module docstrings; docstrings on public classes/methods only; private helpers (`_move`, `_fmt`, `_go_to_*`, `_copy_*`) have NO docstrings — names are self-documenting.
- Imports order: `__future__` → stdlib → third-party → local, blank line between groups.
- Double quotes, 4-space indent, trailing commas in multi-line collections (Black-ish).
- **Do NOT add comments** unless asked (project convention — keep diff noise low).
- Error handling: backend raises; `main()` catches `(FileNotFoundError, ValueError)` and prints `angoor: <msg>` to stderr with exit 1. In-app runtime guards use early `return`; user feedback via `self.notify(..., severity="warning")`.

## Gotchas

- **`_serach_active` is misspelled** (not `search`) — keep the typo or rename ALL 4 sites at once (`on_key`, `_start_search` callers, `action_cancel_search`). It's load-bearing.
- **Malformed 2-key chords are silently dropped** (e.g. `gq` → `_pending="g"`, then `q` is dispatched to the `g` branch, finds no `g`→ nothing happens AND `q` is swallowed — it does NOT quit). This matches vim feel but is a subtle UX trap.
- **No CI / pre-commit / tests**. No `argparse` — `main()` reads `sys.argv[1]` directly; no `--help`, single positional path only.
- `__init__.py` eagerly imports `ViewerApp` and `main` from `.app`, so `import angoor` pulls in Textual (non-trivial startup cost). Intentional.
- DuckDB parse/format errors at load time are NOT caught by `main()` (only `FileNotFoundError`/`ValueError` are) — they'd traceback. If you add new load-time failure modes, extend the except clause.

## Dependencies

```toml
# pyproject.toml
textual >= 0.86.0    # frontend (resolved: 8.2.8)
duckdb  >= 1.1.0     # backend  (resolved: 1.5.4)
# dev = [] (empty)
```

Transitive: `rich`, `typing-extensions`, `platformdirs`, `markdown-it-py`, `pygments`, etc.

## When making changes

1. Mimic existing code style — double quotes, type hints, `from __future__ import annotations`.
2. For new 2-key chords, extend `self._pending` + `_handle_followup`; for single keys, add to `_handle_single`.
3. For new punctuation keys, rely on `glyph = event.character or event.key` (don't switch to `event.key`).
4. Test manually: `uv run angoor test-data/carrier_lookup.csv` and `uv run angoor test-data/0.parquet`.
5. Verify the app boots headlessly with Textual's test pilot: `uv run python -c "import asyncio; from angoor.app import ViewerApp; ..."` — see git history for the pattern used.
6. Do NOT commit changes unless explicitly asked.