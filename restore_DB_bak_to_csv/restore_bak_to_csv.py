#!/usr/bin/env python3
"""Restore a SQL Server .bak file and export every user table to CSV.

Usage:
  ./restore_bak_to_csv.py /path/to/backup.bak
  ./restore_bak_to_csv.py /path/to/backup.bak --out ./my_csv_folder
  ./restore_bak_to_csv.py /path/to/backup.bak --keep-db --keep-container

Requires:
  - Docker Desktop running
  - Python 3 (pymssql + pandas are auto-installed if missing)
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

CONTAINER = os.environ.get("BAK_RESTORE_CONTAINER", "bak-restore-sql")
IMAGE = "mcr.microsoft.com/mssql/server:2022-latest"
SA_PASSWORD = os.environ.get("MSSQL_SA_PASSWORD", "BakRestore_P@ssw0rd!")
HOST_PORT = int(os.environ.get("MSSQL_PORT", "1433"))
VOLUME = "bak-restore-sqldata"
CHUNK_ROWS = 200_000
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], check: bool = True, capture: bool = False, **kwargs):
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
        **kwargs,
    )


def docker_ok() -> None:
    try:
        r = run(["docker", "info"], check=False, capture=True)
    except FileNotFoundError:
        die("Docker is not installed or not on PATH.")
    if r.returncode != 0:
        die("Docker is not running. Start Docker Desktop and retry.")


def ensure_deps() -> None:
    try:
        import pandas  # noqa: F401
        import pymssql  # noqa: F401
    except ImportError:
        print("Installing pymssql and pandas ...")
        run([sys.executable, "-m", "pip", "install", "-q", "pymssql", "pandas"])


def mssql_connect(database: str = "master"):
    import pymssql

    last_err = None
    for _ in range(30):
        try:
            return pymssql.connect(
                server="127.0.0.1",
                port=HOST_PORT,
                user="SA",
                password=SA_PASSWORD,
                database=database,
                login_timeout=5,
                timeout=0,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2)
    die(f"Could not connect to SQL Server on port {HOST_PORT}: {last_err}")


def sqlcmd(query: str) -> None:
    r = run(
        [
            "docker",
            "exec",
            CONTAINER,
            SQLCMD,
            "-S",
            "localhost",
            "-U",
            "SA",
            "-P",
            SA_PASSWORD,
            "-C",
            "-b",
            "-Q",
            query,
        ],
        check=False,
        capture=True,
    )
    if r.returncode != 0:
        die(f"sqlcmd failed:\n{(r.stderr or '')}\n{(r.stdout or '')}")


def wait_for_sql(timeout: int = 180) -> None:
    print("Waiting for SQL Server ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = run(
            [
                "docker",
                "exec",
                CONTAINER,
                SQLCMD,
                "-S",
                "localhost",
                "-U",
                "SA",
                "-P",
                SA_PASSWORD,
                "-C",
                "-b",
                "-Q",
                "SELECT 1",
            ],
            check=False,
            capture=True,
        )
        if r.returncode == 0:
            print("SQL Server is ready.")
            return
        time.sleep(2)
    die("Timed out waiting for SQL Server to become ready.")


def container_exists() -> bool:
    r = run(
        ["docker", "inspect", CONTAINER],
        check=False,
        capture=True,
    )
    return r.returncode == 0


def container_running() -> bool:
    r = run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
        check=False,
        capture=True,
    )
    return r.returncode == 0 and r.stdout.strip().lower() == "true"


def bak_visible(bak_name: str) -> bool:
    r = run(
        ["docker", "exec", CONTAINER, "test", "-f", f"/backups/{bak_name}"],
        check=False,
        capture=True,
    )
    return r.returncode == 0


def stop_conflicting_port() -> None:
    """If another container owns HOST_PORT, stop it so we can bind."""
    r = run(
        ["docker", "ps", "--format", "{{.ID}} {{.Names}} {{.Ports}}"],
        check=False,
        capture=True,
    )
    if r.returncode != 0:
        return
    needle = f":{HOST_PORT}->"
    for line in r.stdout.splitlines():
        if needle not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if name == CONTAINER:
            continue
        print(f"Port {HOST_PORT} is used by container '{name}'; stopping it ...")
        run(["docker", "stop", name], check=False)


def recreate_container(bak_dir: Path) -> None:
    bak_dir = bak_dir.resolve()
    if container_exists():
        print(f"Removing container {CONTAINER} to remount backups ...")
        run(["docker", "rm", "-f", CONTAINER], check=False)

    stop_conflicting_port()
    print(f"Starting SQL Server ({IMAGE}) with backups from {bak_dir} ...")
    run(["docker", "pull", IMAGE], check=False)

    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        f"MSSQL_SA_PASSWORD={SA_PASSWORD}",
        "-e",
        "MSSQL_PID=Developer",
        "-p",
        f"{HOST_PORT}:1433",
        "-v",
        f"{bak_dir}:/backups:ro",
        "-v",
        f"{VOLUME}:/var/opt/mssql",
        IMAGE,
    ]
    if platform.machine().lower() in {"arm64", "aarch64"}:
        # Insert after 'run'
        cmd[2:2] = ["--platform", "linux/amd64"]

    r = run(cmd, check=False, capture=True)
    if r.returncode != 0:
        die(f"Failed to start SQL Server container:\n{r.stderr}")
    wait_for_sql()


def ensure_container(bak_path: Path) -> None:
    bak_dir = bak_path.parent.resolve()
    bak_name = bak_path.name

    if container_running() and bak_visible(bak_name):
        print(f"Reusing running container {CONTAINER}.")
        return

    if container_running() and not bak_visible(bak_name):
        recreate_container(bak_dir)
        return

    if container_exists() and not container_running():
        # Existing stopped container may have wrong mount — recreate to be safe
        recreate_container(bak_dir)
        return

    recreate_container(bak_dir)

    if not bak_visible(bak_name):
        die(
            f"Backup is not visible inside the container at /backups/{bak_name}. "
            f"Ensure the file is directly under {bak_dir}."
        )


def restore_bak(bak_path: Path) -> str:
    bak_in = f"/backups/{bak_path.name}"
    print(f"Inspecting backup: {bak_path}")

    conn = mssql_connect("master")
    cur = conn.cursor()

    cur.execute(f"RESTORE HEADERONLY FROM DISK = N'{bak_in}'")
    header_cols = [d[0] for d in cur.description]
    header = dict(zip(header_cols, cur.fetchone()))
    db_name = header.get("DatabaseName")
    if not db_name:
        die(f"Could not read DatabaseName from backup header. Columns={header_cols}")

    cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{bak_in}'")
    file_cols = [d[0] for d in cur.description]
    file_rows = cur.fetchall()
    conn.close()

    files = [dict(zip(file_cols, row)) for row in file_rows]
    print(f"Database name in backup: {db_name}")
    print(
        "Files: "
        + ", ".join(f"{f['LogicalName']}({f['Type']})" for f in files)
    )

    moves = []
    for f in files:
        logical = f["LogicalName"]
        ftype = str(f["Type"]).strip().upper()
        ext = ".mdf" if ftype == "D" else ".ldf"
        target = f"/var/opt/mssql/data/{db_name}_{logical}{ext}"
        # Sanitize path characters
        target = re.sub(r"[^\w./\-]+", "_", target)
        moves.append(f"MOVE N'{logical}' TO N'{target}'")

    move_sql = ",\n     ".join(moves)
    restore_sql = f"""
RESTORE DATABASE [{db_name}]
FROM DISK = N'{bak_in}'
WITH {move_sql},
     REPLACE, STATS = 5;
"""
    print(f"Restoring [{db_name}] ...")
    r = run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            SQLCMD,
            "-S",
            "localhost",
            "-U",
            "SA",
            "-P",
            SA_PASSWORD,
            "-C",
            "-b",
            "-Q",
            restore_sql,
        ],
        check=False,
    )
    if r.returncode != 0:
        die("RESTORE DATABASE failed.")
    print(f"Restored [{db_name}] successfully.")
    return str(db_name)


def safe_filename(schema: str, table: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", f"{schema}.{table}") + ".csv"


def list_tables(conn) -> list[tuple[str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.name, t.name
        FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE t.type = 'U'
        ORDER BY s.name, t.name
        """
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def export_table_csv(conn, schema: str, table: str, out_path: Path) -> int:
    import pandas as pd

    query = f"SELECT * FROM [{schema}].[{table}]"
    first = True
    total = 0
    for chunk in pd.read_sql(query, conn, chunksize=CHUNK_ROWS):
        for col in chunk.columns:
            if chunk[col].dtype == object:
                chunk[col] = chunk[col].map(
                    lambda v: v.hex()
                    if isinstance(v, (bytes, bytearray, memoryview))
                    else (v.isoformat() if hasattr(v, "isoformat") else v)
                )
        chunk.to_csv(
            out_path,
            index=False,
            mode="w" if first else "a",
            header=first,
            quoting=csv.QUOTE_MINIMAL,
        )
        first = False
        total += len(chunk)

    if first:
        empty = pd.read_sql(f"SELECT TOP 0 * FROM [{schema}].[{table}]", conn)
        empty.to_csv(out_path, index=False)
        return 0
    return total


def export_all_csv(db_name: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "_export_log.tsv"
    print(f"Exporting tables from [{db_name}] -> {out_dir}")

    conn = mssql_connect(db_name)
    tables = list_tables(conn)
    print(f"Found {len(tables)} user tables.")

    ok = err = 0
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        log.write("schema\ttable\trows\tstatus\tseconds\tfile\n")
        for i, (schema, table) in enumerate(tables, 1):
            fname = safe_filename(schema, table)
            out_path = out_dir / fname
            start = time.time()
            try:
                rows = export_table_csv(conn, schema, table, out_path)
                status = "ok"
                ok += 1
            except Exception as exc:  # noqa: BLE001
                rows = -1
                status = f"error: {exc}"
                err += 1
                (out_dir / f"{fname}.ERROR.txt").write_text(status, encoding="utf-8")
            elapsed = time.time() - start
            log.write(f"{schema}\t{table}\t{rows}\t{status}\t{elapsed:.2f}\t{fname}\n")
            log.flush()
            if i % 25 == 0 or rows >= 100_000 or status.startswith("error"):
                print(
                    f"  [{i}/{len(tables)}] {schema}.{table} rows={rows} ({elapsed:.1f}s)"
                )

    conn.close()
    print(f"Export complete: ok={ok} err={err} in {time.time() - t0:.0f}s -> {out_dir}")


def drop_database(db_name: str) -> None:
    print(f"Dropping restored database [{db_name}] ...")
    sqlcmd(
        f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{db_name}];"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a SQL Server .bak and export each table to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  ./restore_bak_to_csv.py ./muscleshoals_NGDM-20240219_200000.bak
  ./restore_bak_to_csv.py /data/db.bak --out ./exports
  MSSQL_PORT=1434 ./restore_bak_to_csv.py ./db.bak --keep-db --keep-container
""",
    )
    parser.add_argument("backup", type=Path, help="Path to the .bak backup file")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for CSV files (default: ./<DatabaseName>_csv)",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the restored database after export",
    )
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Keep the SQL Server Docker container running after export",
    )
    args = parser.parse_args()

    bak = args.backup.expanduser().resolve()
    if not bak.is_file():
        die(f"Backup file not found: {bak}")
    if bak.suffix.lower() != ".bak":
        print(f"Warning: file does not end with .bak: {bak.name}")

    docker_ok()
    ensure_deps()
    ensure_container(bak)

    db_name = restore_bak(bak)
    out_dir = (args.out or (Path.cwd() / f"{db_name}_csv")).expanduser().resolve()
    export_all_csv(db_name, out_dir)

    if not args.keep_db:
        try:
            drop_database(db_name)
        except SystemExit as exc:
            print(f"Warning: could not drop database (exit {exc.code}).")

    if not args.keep_container:
        print(f"Stopping container {CONTAINER} ...")
        run(["docker", "stop", CONTAINER], check=False)

    print("\nDone.")
    print(f"  CSV folder: {out_dir}")
    print(f"  Log file:   {out_dir / '_export_log.tsv'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
