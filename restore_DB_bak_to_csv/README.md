# restore-bak-to-csv

Restore a Microsoft SQL Server `.bak` backup and export **every user table** to its own CSV file.

SQL Server `.bak` files cannot be read directly by DuckDB, Pandas, or most open-source tools. This utility:

1. Starts **SQL Server 2022 in Docker**
2. Restores the `.bak` you pass as an argument
3. Exports each table to `schema.table.csv`
4. Optionally cleans up the restored database and container

Works on macOS (including Apple Silicon), Linux, and Windows (via Docker Desktop / WSL2).

---

## What to copy into an external repo

### Required

| File | Purpose |
|------|---------|
| `restore_bak_to_csv.py` | Main logic: Docker restore + CSV export |
| `restore_bak_to_csv` | Executable bash wrapper (uses `.venv` if present) |
| `requirements.txt` | Python dependencies |
| `README.md` | This documentation |
| `.gitignore` | Keeps backups, secrets, and outputs out of git |

### Do **not** copy

| Path | Why |
|------|-----|
| `*.bak` | Large binary backups; keep outside git (or use LFS / object storage) |
| `.venv/` | Local virtualenv; recreate with `pip install -r requirements.txt` |
| `.mssql_sa_password` | Secret |
| `*_csv/`, parquet folders, `*.duckdb` | Generated outputs |
| `export_*.log` | Local run logs |
| `export_tables.py` | Optional older helper (Parquet/DuckDB). Only include if you want that path too |

### Suggested repo layout

```text
restore-bak-to-csv/
├── README.md
├── requirements.txt
├── .gitignore
├── restore_bak_to_csv          # chmod +x
└── restore_bak_to_csv.py
```

---

## Requirements

- **Docker Desktop** (or Docker Engine) running
- **Python 3.9+**
- Network access the first time to pull `mcr.microsoft.com/mssql/server:2022-latest`
- Enough disk for: backup size + restored DB files + CSV output

On Apple Silicon the script runs SQL Server with `--platform linux/amd64` (Rosetta/emulation).

---

## Setup

```bash
git clone <your-repo-url> restore-bak-to-csv
cd restore-bak-to-csv

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

chmod +x restore_bak_to_csv restore_bak_to_csv.py
```

---

## Usage

```bash
# Basic: restore backup and write CSVs to ./<DatabaseName>_csv/
./restore_bak_to_csv /path/to/database.bak

# Custom output folder
./restore_bak_to_csv /path/to/database.bak --out ./exports/mydb

# Keep restored DB + container for further SQL work
./restore_bak_to_csv /path/to/database.bak --keep-db --keep-container
```

Or call Python directly:

```bash
python restore_bak_to_csv.py /path/to/database.bak --out ./exports
```

### Arguments

| Argument | Description |
|----------|-------------|
| `backup` | Path to the `.bak` file (**required**) |
| `--out DIR` | CSV output directory (default: `./<DatabaseName>_csv`) |
| `--keep-db` | Do not drop the restored database after export |
| `--keep-container` | Leave the Docker SQL Server container running |

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MSSQL_SA_PASSWORD` | `BakRestore_P@ssw0rd!` | SA password for the Docker SQL instance |
| `MSSQL_PORT` | `1433` | Host port mapped to SQL Server |
| `BAK_RESTORE_CONTAINER` | `bak-restore-sql` | Docker container name |

Example:

```bash
MSSQL_PORT=1434 MSSQL_SA_PASSWORD='Your_Str0ng_Pass!' \
  ./restore_bak_to_csv ./db.bak --keep-db --keep-container
```

---

## Output

For a backup whose database name is `MyDatabase`:

```text
MyDatabase_csv/
├── _export_log.tsv          # schema, table, row count, status, timing
├── dbo.Customers.csv
├── dbo.Orders.csv
└── ...
```

- One CSV per user table (`schema.table.csv`)
- Empty tables still get a header-only CSV
- Failed tables write a `*.csv.ERROR.txt` sidecar and are logged in `_export_log.tsv`

---

## How it works

```text
.bak file
   │
   ▼
Docker SQL Server 2022  ── RESTORE DATABASE ──► restored DB
   │
   ▼
pymssql + pandas        ── SELECT * per table ──► schema.table.csv
```

1. Ensures a SQL Server container is running with the backup’s parent directory mounted at `/backups`
2. Reads `RESTORE HEADERONLY` / `FILELISTONLY` to get the database name and logical file names
3. Restores with `MOVE` into `/var/opt/mssql/data`
4. Lists all user tables and streams each to CSV in chunks
5. Drops the DB and stops the container unless you pass `--keep-db` / `--keep-container`

---

## Notes & limitations

- Only **SQL Server `.bak`** full database backups are supported (not differential/log-only as the sole input).
- Very large tables are streamed in chunks (`200_000` rows) to limit memory use.
- Binary / unusual column types are stringified (e.g. bytes → hex) for CSV safety.
- If port `1433` is already in use by another container, the script stops that container so it can bind the port (or set `MSSQL_PORT` to something else).
- The Docker volume `bak-restore-sqldata` persists SQL data files between runs. To fully reset:

  ```bash
  docker rm -f bak-restore-sql
  docker volume rm bak-restore-sqldata
  ```

---

## License

Add your preferred license before publishing the external repository.
