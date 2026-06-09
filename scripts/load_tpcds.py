"""
Load TPC-DS data into the lab warehouse.

Uses DuckDB's built-in `tpcds` extension (dsdgen) to generate data at a
target scale factor and exports each table as Parquet under
`data/raw/tpcds_sf<sf>/<table>.parquet`. The Parquet files are
consumable by both DuckDB and PySpark for downstream experiments.

Scale factor reference (approximate on-disk Parquet size):
    sf=0.01  ~  10 MB
    sf=0.1   ~ 100 MB   <-- default
    sf=1     ~   1 GB

Usage:
    python scripts/load_tpcds.py                # default sf=0.1
    python scripts/load_tpcds.py --sf 0.01
    python scripts/load_tpcds.py --sf 0.1 --out data/raw
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "raw"
DEFAULT_DB = REPO_ROOT / "data" / "warehouse" / "tpcds.duckdb"


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PB"


def generate_tpcds(con: duckdb.DuckDBPyConnection, sf: float) -> list[str]:
    print(f"[1/3] Installing/loading tpcds extension...")
    con.execute("INSTALL tpcds;")
    con.execute("LOAD tpcds;")

    print(f"[2/3] Generating TPC-DS data at sf={sf} (this may take a minute)...")
    t0 = time.time()
    con.execute(f"CALL dsdgen(sf={sf});")
    print(f"      ...done in {time.time() - t0:.1f}s")

    tables = [
        r[0]
        for r in con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        ).fetchall()
    ]
    return tables


def export_parquet(
    con: duckdb.DuckDBPyConnection, tables: list[str], out_dir: Path
) -> None:
    print(f"[3/3] Exporting {len(tables)} tables to {out_dir}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    for t in tables:
        target = out_dir / f"{t}.parquet"
        con.execute(
            f"COPY (SELECT * FROM {t}) TO '{target.as_posix()}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD);"
        )
        size = target.stat().st_size
        total_bytes += size
        rows = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"      {t:30s} rows={rows:>12,}   parquet={human_bytes(size)}")

    print(f"\nTotal parquet on disk: {human_bytes(total_bytes)}")


def main() -> int:
    p = argparse.ArgumentParser(description="Load TPC-DS data via DuckDB.")
    p.add_argument("--sf", type=float, default=0.1, help="Scale factor (default 0.1 ~= 100MB).")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Parquet output dir.")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="DuckDB file to persist tables in.")
    p.add_argument("--in-memory", action="store_true", help="Skip persistent DuckDB file.")
    args = p.parse_args()

    out_dir = args.out / f"tpcds_sf{args.sf}"

    if args.in_memory:
        con = duckdb.connect()
    else:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        if args.db.exists():
            args.db.unlink()
        con = duckdb.connect(str(args.db))
        print(f"DuckDB warehouse: {args.db}")

    try:
        tables = generate_tpcds(con, args.sf)
        export_parquet(con, tables, out_dir)
    finally:
        con.close()

    print(f"\nDone. Parquet at: {out_dir}")
    if not args.in_memory:
        print(f"DuckDB at:       {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
