# SQL Server `.bak` → Parquet / CSV

Self-contained exporter for this repo. Restore any SQL Server `.bak` in Docker and write **Parquet**, **CSV**, or both. After a successful export it **removes the SQL Server container and data volume** so Docker disk is freed.

Host dependency: **Docker only**.

```text
.bak → Docker SQL Server (restore) → tables as parquet and/or csv
     → legacy_database.md + er_diagram.md
     → drop SQL container + volume (unless --keep-sqlserver)
```

## Quick start

```bash
chmod +x restore_bak_to_csv restore_bak_to_csv.py mssql_bak_to_parquet.sh mssql_bak_export.sh

# CSV (default)
./restore_bak_to_csv.py ./database.bak --out ./exports

# Parquet
./restore_bak_to_csv.py ./database.bak --format parquet

# Both
./restore_bak_to_csv.py ./database.bak --format both --out ./export
```

Same engine, format-neutral name:

```bash
./mssql_bak_export.sh ./database.bak --format parquet
./mssql_bak_export.sh ./database.bak --format csv
```

## What you get

| Feature | Default |
| --- | --- |
| `--format parquet\|csv\|both` | `csv` via `restore_bak_to_csv`; `parquet` via `mssql_bak_export.sh` |
| Typed export (CAST for xml/geography/etc.) | yes |
| `legacy_database.md` + Mermaid ER | yes (`--skip-docs` to skip) |
| Remove SQL container + named volume after run | yes |
| Keep SQL Server for a second pass | `--keep-sqlserver` |

Output layout:

```text
<bak-stem>_export/
  tables/dbo/Employees.parquet   # and/or .csv
  export_manifest.csv
  legacy_database.md
  er_diagram.md
  schema_catalog.json
```

## Docker cleanup

A restored database is usually several times the `.bak` size and lives in a Docker **named volume**. `docker rm` alone does not free that.

This tool:

1. Deletes leftover container/volume from the **previous** run at start
2. Deletes container, `mssql_bak_*_data` volumes, and the unused tool network after a **successful** export

SQL Server and exporter **images** stay (re-pull is slow). To keep the restored DB: `--keep-sqlserver`.

## Files in this folder

| File | Role |
| --- | --- |
| `restore_bak_to_csv.py` | CLI (default `--format csv`); runs the Docker exporter |
| `restore_bak_to_csv` | Same CLI as a bash wrapper |
| `mssql_bak_to_parquet.sh` | Restore + parquet/csv export + Docker volume cleanup |
| `mssql_bak_export.sh` | Same script, shorter name |
| `export_all_tables.py` / `Dockerfile` | Exporter image (ODBC + PyArrow) |
| `legacy_catalog.py` | Catalog markdown + ER |
