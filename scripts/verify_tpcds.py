"""
Quick sanity check that the generated TPC-DS Parquet is readable by
both DuckDB and PySpark.

    python scripts/verify_tpcds.py --sf 0.1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]


def check_duckdb(parquet_dir: Path) -> None:
    print(f"\n== DuckDB ==")
    con = duckdb.connect()
    files = sorted(parquet_dir.glob("*.parquet"))
    print(f"Found {len(files)} parquet files in {parquet_dir}")
    # Sample query against store_sales fact if present.
    ss = parquet_dir / "store_sales.parquet"
    if ss.exists():
        n = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{ss.as_posix()}')"
        ).fetchone()[0]
        print(f"store_sales rows (DuckDB): {n:,}")
    con.close()


def check_spark(parquet_dir: Path) -> None:
    print(f"\n== PySpark ==")
    try:
        from pyspark.sql import SparkSession
    except Exception as e:  # pragma: no cover
        print(f"PySpark not available: {e}")
        return

    try:
        spark = (
            SparkSession.builder.appName("tpcds-verify")
            .master("local[*]")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.ui.showConsoleProgress", "false")
            .getOrCreate()
        )
    except Exception as e:
        print(f"Could not start Spark (is a JDK installed and JAVA_HOME set?): {e}")
        return

    spark.sparkContext.setLogLevel("WARN")
    try:
        ss = parquet_dir / "store_sales.parquet"
        if ss.exists():
            df = spark.read.parquet(str(ss))
            print(f"store_sales rows (Spark):  {df.count():,}")
            df.printSchema()
    finally:
        spark.stop()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sf", type=float, default=0.1)
    p.add_argument("--root", type=Path, default=REPO_ROOT / "data" / "raw")
    args = p.parse_args()

    parquet_dir = args.root / f"tpcds_sf{args.sf}"
    if not parquet_dir.exists():
        raise SystemExit(f"Not found: {parquet_dir}. Run load_tpcds.py first.")

    check_duckdb(parquet_dir)
    check_spark(parquet_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
