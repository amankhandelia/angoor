# angoor

A lightweight TUI for inspecting CSV and Parquet files with VIM-style keybindings.
Built with [Textual](https://textual.textualize.io/) for the frontend and
[DuckDB](https://duckdb.org/) for the backend.

## Features (MVP)

| Key | Action |
| --- | --- |
| `h` `j` `k` `l` | Move cell cursor left/down/up/right |
| `gg` | Go to the first row |
| `gh` | Go to the header (column names) |
| `G` | Go to the last row |
| `^` | Go to the start of the row (column 0) |
| `$` | Go to the end of the row (last column) |
| `yw` | Copy the active cell |
| `yc` | Copy the whole active column |
| `yy` | Copy the whole active row (comma-separated) |
| `v` | View the full cell text in a popup (Esc to close) |
| `/` | Search within the active row (with incremental input) |
| `//` | Search within the active column |
| `n` | Repeat the last search |
| `q` | Quit |
| `Esc` | Cancel search input |
| `Ctrl+C` | Quit |

The first column is a headerless row index. Long cell values are middle
truncated (`start…end`) for display; `v` reveals the full content. A
lazygit-style help footer is pinned to the bottom of the screen.

## Run

```bash
# using uv (recommended)
uv run angoor path/to/data.csv
uv run angoor path/to/data.parquet

# or as a module
uv run python -m angoor path/to/data.parquet
```

The clipboard uses Textual's `copy_to_clipboard` support (OSC52 on terminals
that allow it).