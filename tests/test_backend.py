"""Regression tests for the DuckDB-backed `load_table` loader."""

from __future__ import annotations

from decimal import Decimal

import pytest

from angoor.backend import UnsupportedFileError, load_table


def test_load_csv_columns_and_rows(sample_csv):
    """CSV is parsed with header names and rows in declared column order."""
    columns, rows = load_table(sample_csv)

    assert columns == ["id", "name", "category", "price", "active"]
    assert len(rows) == 5
    assert rows[0] == (1, "Widget Alpha", "tools", 9.99, True)
    assert rows[-1][1] == "Doohickey Epsilon"


def test_load_csv_preserves_null(sample_csv):
    """Empty cells come back as None, not the string 'None'."""
    _, rows = load_table(sample_csv)
    assert rows[4][3] is None


def test_load_tsv(sample_tsv):
    """Tab-separated files are routed through the same CSV auto reader."""
    columns, rows = load_table(sample_tsv)
    assert columns == ["code", "description"]
    assert rows[0] == ("01Q", "Titan Airways")
    assert len(rows) == 4


def test_load_parquet_matches_csv_schema(sample_parquet):
    """The Parquet fixture carries the same columns as the CSV fixture."""
    columns, rows = load_table(sample_parquet)
    assert columns == ["id", "name", "category", "price", "active"]
    assert len(rows) == 5
    assert rows[0][1] == "Widget Alpha"


def test_load_parquet_decimals(sample_parquet):
    """Parquet stores decimals natively rather than as strings."""
    _, rows = load_table(sample_parquet)
    assert isinstance(rows[0][3], Decimal)
    assert rows[0][3] == Decimal("9.99")
    assert rows[4][3] is None


def test_load_table_accepts_str_path(sample_csv):
    """load_table accepts a plain str, not just Path objects."""
    columns, _ = load_table(str(sample_csv))
    assert columns[0] == "id"


def test_load_table_missing_file_raises(missing_path):
    """A non-existent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as excinfo:
        load_table(missing_path)
    assert "not found" in str(excinfo.value).lower()


def test_load_table_unsupported_extension_raises(unsupported_path):
    """An unknown extension raises UnsupportedFileError (a ValueError subclass)."""
    with pytest.raises(UnsupportedFileError) as excinfo:
        load_table(unsupported_path)
    assert unsupported_path.suffix in str(excinfo.value)
    assert issubclass(UnsupportedFileError, ValueError)


def test_missing_file_message_mentions_resolved_path(missing_path):
    """The error message echoes the resolved absolute path for easy debugging."""
    with pytest.raises(FileNotFoundError) as excinfo:
        load_table(missing_path)
    assert str(missing_path.resolve()) in str(excinfo.value)


def test_rows_are_tuples(sample_csv):
    """All rows are returned as tuples (not lists), matching the contract."""
    _, rows = load_table(sample_csv)
    assert all(isinstance(r, tuple) for r in rows)