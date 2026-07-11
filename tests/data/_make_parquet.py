"""Generate a small deterministic Parquet fixture for tests."""
from __future__ import annotations

from pathlib import Path

import duckdb


def main() -> None:
    out = Path(__file__).parent / "sample.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE items AS
            SELECT * FROM (VALUES
                (1, 'Widget Alpha',   'tools',       9.99,  TRUE),
                (2, 'Widget Beta',    'tools',       14.50, FALSE),
                (3, 'Gadget Gamma',   'electronics', 7.00,  TRUE),
                (4, 'Gadget Delta',   'electronics', 12.25, TRUE),
                (5, 'Doohickey Epsilon', 'misc',      NULL,  FALSE)
            ) AS t(id, name, category, price, active)
            """
        )
        con.execute(f"COPY items TO '{out}' (FORMAT PARQUET)")
    finally:
        con.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()