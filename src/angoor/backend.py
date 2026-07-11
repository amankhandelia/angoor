"""DuckDB-backed loader for CSV and Parquet files."""

from __future__ import annotations

from pathlib import Path

import duckdb

_READERS = {
    ".csv": "read_csv_auto",
    ".tsv": "read_csv_auto",
    ".parquet": "read_parquet",
    ".pq": "read_parquet",
}


class UnsupportedFileError(ValueError):
    """Raised when the file extension is not CSV or Parquet."""


def load_table(path: str | Path) -> tuple[list[str], list[tuple]]:
    """Load a CSV/Parquet file via DuckDB.

    Returns a tuple of (column_names, rows) where rows is a list of tuples
    matching the column order.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    reader = _READERS.get(p.suffix.lower())
    if reader is None:
        raise UnsupportedFileError(
            f"Unsupported file type: {p.suffix!r}. Supported: csv, parquet"
        )

    con = duckdb.connect()
    try:
        # Use a parameter for the path; DuckDB supports bind parameters for
        # the table-function argument.
        result = con.execute(f"SELECT * FROM {reader}(?)", [str(p)])
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
    finally:
        con.close()

    return columns, rows