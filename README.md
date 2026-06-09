# dw-lab

Sandbox for experimenting with data-warehouse structure and automation
patterns. Uses **DuckDB** for fast local SQL + **PySpark** for distributed-
style pipeline patterns, sharing the same Parquet data lake on disk.

```
dw-lab/
├── data/
│   ├── raw/            # generated TPC-DS parquet (gitignored)
│   └── warehouse/      # persistent duckdb files (gitignored)
├── notebooks/          # jupyter scratch
├── scripts/
│   ├── load_tpcds.py   # generate + export TPC-DS at any scale factor
│   └── verify_tpcds.py # smoke test (DuckDB + Spark read the parquet)
├── requirements.txt
└── README.md
```

## Setup

```powershell
cd dw-lab
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

PySpark 4.x is required for Python 3.13+. A JDK (17+) must be on PATH
for the Spark verify step; the DuckDB path has no Java dependency.

## Generate TPC-DS (~100 MB)

```powershell
python scripts/load_tpcds.py              # default sf=0.1 (~100 MB parquet)
python scripts/load_tpcds.py --sf 0.01    # tiny (~10 MB) for quick loops
```

Output:
- `data/raw/tpcds_sf0.1/<table>.parquet` — 24 tables, ZSTD-compressed
- `data/warehouse/tpcds.duckdb`           — same tables persisted in DuckDB

## Verify

```powershell
python scripts/verify_tpcds.py --sf 0.1
```

## Why DuckDB for generation?

DuckDB ships an in-process `tpcds` extension (`CALL dsdgen(sf=...)`)
that generates the full TPC-DS schema without compiling the reference
`dsdgen` C tool. The resulting tables are exported to Parquet so any
engine (Spark, Polars, Trino, etc.) can consume them.
