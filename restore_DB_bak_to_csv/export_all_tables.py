#!/usr/bin/env python3
"""Export all user tables from a SQL Server database to Parquet and/or CSV."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyodbc

from legacy_catalog import write_legacy_docs


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# SQL Server types that pyodbc/Arrow handle poorly as native values.
CAST_AS_NVARCHAR_MAX = {
    "xml",
    "sql_variant",
    "hierarchyid",
    "geography",
    "geometry",
    "datetimeoffset",
    "time",
}
CAST_AS_VARBINARY = {"timestamp", "rowversion"}


@dataclass
class ColumnMeta:
    name: str
    type_name: str
    max_length: int | None
    precision: int | None
    scale: int | None
    is_nullable: bool


@dataclass
class TableResult:
    schema: str
    table: str
    row_count: int | None
    output_path: str | None
    status: str
    error: str | None = None
    seconds: float | None = None
    csv_path: str | None = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True, help="SQL Server hostname")
    p.add_argument("--port", default="1433", help="SQL Server port")
    p.add_argument("--database", required=True, help="Database name")
    p.add_argument("--user", default="sa")
    p.add_argument("--password", required=True)
    p.add_argument("--out", required=True, help="Output directory for table files")
    p.add_argument(
        "--format",
        default="parquet",
        choices=["parquet", "csv", "both"],
        help="Export format (default: parquet)",
    )
    p.add_argument(
        "--schemas",
        default="",
        help="Comma-separated schema allow-list (default: all non-system schemas)",
    )
    p.add_argument(
        "--tables",
        default="",
        help="Comma-separated schema.table allow-list (default: all tables in selected schemas)",
    )
    p.add_argument(
        "--exclude-schemas",
        default="sys,INFORMATION_SCHEMA",
        help="Comma-separated schemas to skip",
    )
    p.add_argument(
        "--chunksize",
        type=int,
        default=50_000,
        help="Pandas read chunk size for large tables",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-export tables even if output files already exist",
    )
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first table export failure",
    )
    p.add_argument(
        "--skip-docs",
        action="store_true",
        help="Skip ER diagram and legacy_database.md catalog",
    )
    return p.parse_args()


def connect(args: argparse.Namespace) -> pyodbc.Connection:
    # ODBC Driver 18 requires TrustServerCertificate for local/dev containers.
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={args.host},{args.port};"
        f"DATABASE={args.database};"
        f"UID={args.user};"
        f"PWD={args.password};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    last_err: Exception | None = None
    for attempt in range(1, 31):
        try:
            return pyodbc.connect(conn_str, timeout=10)
        except Exception as exc:  # noqa: BLE001 - retry loop for container startup
            last_err = exc
            print(f"[export] connection attempt {attempt}/30 failed: {exc}", flush=True)
            time.sleep(2)
    raise RuntimeError(f"Could not connect to SQL Server: {last_err}")


def split_csv(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def parse_formats(value: str) -> set[str]:
    if value == "both":
        return {"parquet", "csv"}
    return {value}


def safe_path_part(name: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", name).strip("._")
    return cleaned or "unnamed"


def list_tables(
    conn: pyodbc.Connection,
    include_schemas: set[str],
    exclude_schemas: set[str],
) -> list[tuple[str, str]]:
    sql = """
    SELECT s.name AS schema_name, t.name AS table_name
    FROM sys.tables AS t
    INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    WHERE t.is_ms_shipped = 0
    ORDER BY s.name, t.name
    """
    cur = conn.cursor()
    cur.execute(sql)
    tables: list[tuple[str, str]] = []
    for schema_name, table_name in cur.fetchall():
        if schema_name in exclude_schemas:
            continue
        if include_schemas and schema_name not in include_schemas:
            continue
        tables.append((schema_name, table_name))
    return tables


def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def fetch_row_count(conn: pyodbc.Connection, schema: str, table: str) -> int | None:
    sql = f"SELECT COUNT_BIG(*) FROM {quote_ident(schema)}.{quote_ident(table)}"
    try:
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        return int(row[0]) if row is not None else None
    except Exception:  # noqa: BLE001
        return None


def get_column_metadata(
    conn: pyodbc.Connection, schema: str, table: str
) -> list[ColumnMeta]:
    sql = """
    SELECT
        c.name AS column_name,
        ty.name AS type_name,
        c.max_length,
        c.precision,
        c.scale,
        c.is_nullable
    FROM sys.columns AS c
    INNER JOIN sys.tables AS t ON t.object_id = c.object_id
    INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    INNER JOIN sys.types AS ty
        ON ty.user_type_id = c.user_type_id
    WHERE s.name = ? AND t.name = ?
    ORDER BY c.column_id
    """
    cur = conn.cursor()
    cur.execute(sql, schema, table)
    cols: list[ColumnMeta] = []
    for name, type_name, max_length, precision, scale, is_nullable in cur.fetchall():
        cols.append(
            ColumnMeta(
                name=name,
                type_name=str(type_name).lower(),
                max_length=int(max_length) if max_length is not None else None,
                precision=int(precision) if precision is not None else None,
                scale=int(scale) if scale is not None else None,
                is_nullable=bool(is_nullable),
            )
        )
    return cols


def get_column_names(conn: pyodbc.Connection, schema: str, table: str) -> list[str]:
    return [c.name for c in get_column_metadata(conn, schema, table)]


def select_expression(col: ColumnMeta) -> str:
    """Build a SELECT expression that avoids unsupported ODBC native types."""
    ident = quote_ident(col.name)
    t = col.type_name
    if t in CAST_AS_NVARCHAR_MAX:
        if t in {"geography", "geometry"}:
            return (
                f"CASE WHEN {ident} IS NULL THEN NULL "
                f"ELSE CAST({ident}.STAsText() AS NVARCHAR(MAX)) END AS {ident}"
            )
        return f"CAST({ident} AS NVARCHAR(MAX)) AS {ident}"
    if t in CAST_AS_VARBINARY:
        return f"CONVERT(VARBINARY(8), {ident}) AS {ident}"
    # nvarchar(max)/varchar(max)/varbinary(max) sometimes trip older bindings;
    # explicit CAST keeps driver behavior stable.
    if t in {"nvarchar", "varchar", "nchar", "char"} and col.max_length == -1:
        return f"CAST({ident} AS NVARCHAR(MAX)) AS {ident}"
    if t in {"varbinary", "binary", "image"} and (col.max_length or 0) in (-1, 2147483647):
        return f"CAST({ident} AS VARBINARY(MAX)) AS {ident}"
    return ident


def build_select_sql(schema: str, table: str, columns: list[ColumnMeta]) -> str:
    fq = f"{quote_ident(schema)}.{quote_ident(table)}"
    if not columns:
        return f"SELECT * FROM {fq}"
    exprs = ", ".join(select_expression(c) for c in columns)
    return f"SELECT {exprs} FROM {fq}"


def arrow_type_for_column(col: ColumnMeta) -> pa.DataType:
    t = col.type_name
    if t in {"bigint"}:
        return pa.int64()
    if t in {"int"}:
        return pa.int32()
    if t in {"smallint", "tinyint"}:
        return pa.int16()
    if t in {"bit"}:
        return pa.bool_()
    if t in {"float"}:
        return pa.float64()
    if t in {"real"}:
        return pa.float32()
    if t in {"money"}:
        return pa.decimal128(19, 4)
    if t in {"smallmoney"}:
        return pa.decimal128(10, 4)
    if t in {"decimal", "numeric"}:
        precision = min(max(col.precision or 38, 1), 38)
        scale = min(max(col.scale or 0, 0), precision)
        return pa.decimal128(precision, scale)
    if t in {"date"}:
        return pa.date32()
    if t in {"datetime", "datetime2", "smalldatetime"}:
        return pa.timestamp("us")
    if t in CAST_AS_VARBINARY or t in {"binary", "varbinary", "image"}:
        return pa.binary()
    # Strings / cast-to-text types / uniqueidentifier / defaults
    return pa.string()


def build_arrow_schema(columns: list[ColumnMeta]) -> pa.Schema:
    # Always nullable: chunk nullability varies and must not break ParquetWriter.
    fields = [
        pa.field(c.name, arrow_type_for_column(c), nullable=True) for c in columns
    ]
    return pa.schema(fields)


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def normalize_dataframe(df: pd.DataFrame, columns: list[ColumnMeta]) -> pd.DataFrame:
    """Coerce SQL Server values into parquet-friendly Python/Arrow types."""
    out = df.copy()
    meta_by_name = {c.name: c for c in columns}

    for col_name in out.columns:
        series = out[col_name]
        meta = meta_by_name.get(col_name)
        type_name = meta.type_name if meta else ""

        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if pd.api.types.is_bool_dtype(series):
            continue

        # Preserve numerics already decoded by pandas/pyodbc.
        if pd.api.types.is_numeric_dtype(series) and type_name not in {
            "decimal",
            "numeric",
            "money",
            "smallmoney",
        }:
            continue

        if series.dtype != object and type_name not in {
            "decimal",
            "numeric",
            "money",
            "smallmoney",
        }:
            continue

        if type_name in {"bigint", "int", "smallint", "tinyint"}:
            out[col_name] = series.map(_to_int)
            continue

        if type_name in {"decimal", "numeric", "money", "smallmoney"}:
            out[col_name] = series.map(_to_decimal)
            continue

        # Object columns: keep Decimal if present; stringify only exotic values.
        sample = [v for v in series.head(200).tolist() if not _is_null(v)]
        if sample and all(isinstance(v, Decimal) for v in sample):
            out[col_name] = series.map(_to_decimal)
            continue

        out[col_name] = series.map(_stringify_cell)
    return out


def _to_decimal(value: Any) -> Decimal | None:
    if _is_null(value):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return Decimal(text)
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    """Coerce driver/pandas quirks like Decimal('23.0') or '2.0' into ints."""
    if _is_null(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return int(Decimal(text))
    return int(value)


def _stringify_cell(value: Any) -> Any:
    if _is_null(value):
        return None
    if isinstance(value, Decimal):
        # Fixed-point text if we ever stringify decimals; prefer _to_decimal path.
        return format(value, "f")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dataframe_to_arrow(df: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    """Convert a chunk to Arrow, locked to the table schema."""
    # Ensure every schema field exists (empty result edge cases).
    for field in schema:
        if field.name not in df.columns:
            df[field.name] = None
    df = df[[field.name for field in schema]]

    arrays: list[pa.Array] = []
    for field in schema:
        series = df[field.name]
        values = series.tolist()
        try:
            if pa.types.is_integer(field.type):
                values = [_to_int(v) for v in values]
            elif pa.types.is_decimal(field.type):
                values = [_to_decimal(v) for v in values]
            arrays.append(pa.array(values, type=field.type))
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError):
            # Last-resort: cast via string then to target when possible.
            if pa.types.is_integer(field.type):
                int_values = [_to_int(v) for v in values]
                arrays.append(pa.array(int_values, type=field.type))
            elif pa.types.is_decimal(field.type):
                dec_values = [_to_decimal(v) for v in values]
                arrays.append(pa.array(dec_values, type=field.type))
            elif pa.types.is_binary(field.type):
                bin_values = [
                    None
                    if _is_null(v)
                    else (v if isinstance(v, (bytes, bytearray)) else str(v).encode())
                    for v in values
                ]
                arrays.append(pa.array(bin_values, type=field.type))
            else:
                str_values = [None if _is_null(v) else str(v) for v in values]
                arrays.append(pa.array(str_values, type=pa.string()))
    # Rebuild with possibly softened types only if lengths match schema.
    try:
        return pa.Table.from_arrays(arrays, schema=schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError):
        soft_fields = []
        for field, arr in zip(schema, arrays):
            soft_fields.append(pa.field(field.name, arr.type, nullable=True))
        return pa.Table.from_arrays(arrays, schema=pa.schema(soft_fields))


def _csv_cell(value: Any) -> Any:
    if _is_null(value):
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def dataframe_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col_name in out.columns:
        out[col_name] = out[col_name].map(_csv_cell)
    return out


def write_csv_chunk(df: pd.DataFrame, path: Path, *, header: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe_for_csv(df).to_csv(
        path,
        index=False,
        mode="w" if header else "a",
        header=header,
        quoting=csv.QUOTE_MINIMAL,
        encoding="utf-8",
    )


def write_empty_csv(path: Path, columns: list[ColumnMeta] | Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [c.name if isinstance(c, ColumnMeta) else str(c) for c in columns]
    pd.DataFrame(columns=names).to_csv(path, index=False, encoding="utf-8")


def write_error_sidecar(path: Path, message: str) -> None:
    sidecar = path.with_name(path.stem + ".ERROR.txt")
    sidecar.write_text(message, encoding="utf-8")


def write_empty_parquet(path: Path, columns: list[ColumnMeta] | Iterable[str]) -> None:
    cols = list(columns)
    if not cols:
        table = pa.table({"_no_columns": pa.array([], type=pa.string())})
        pq.write_table(table, path)
        return

    if isinstance(cols[0], ColumnMeta):
        schema = build_arrow_schema(cols)  # type: ignore[arg-type]
        table = schema.empty_table()
    else:
        arrays = [pa.array([], type=pa.string()) for _ in cols]
        table = pa.table(dict(zip([str(c) for c in cols], arrays)))
    pq.write_table(table, path)


def export_table(
    conn: pyodbc.Connection,
    schema: str,
    table: str,
    parquet_path: Path | None,
    csv_path: Path | None,
    chunksize: int,
) -> TableResult:
    started = time.time()
    target_dir = (parquet_path or csv_path).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    row_count = fetch_row_count(conn, schema, table)
    columns = get_column_metadata(conn, schema, table)
    arrow_schema = build_arrow_schema(columns) if columns else pa.schema([])

    try:
        if row_count == 0:
            if parquet_path is not None:
                write_empty_parquet(parquet_path, columns)
            if csv_path is not None:
                write_empty_csv(csv_path, columns)
            return TableResult(
                schema=schema,
                table=table,
                row_count=0,
                output_path=str(parquet_path) if parquet_path else str(csv_path),
                status="ok_empty",
                seconds=round(time.time() - started, 3),
                csv_path=str(csv_path) if csv_path else None,
            )

        query = build_select_sql(schema, table, columns)
        writer: pq.ParquetWriter | None = None
        written = 0
        csv_header = True
        locked_schema: pa.Schema | None = None
        cur = conn.cursor()
        cur.execute(query)
        col_names = [desc[0] for desc in cur.description] if cur.description else [
            c.name for c in columns
        ]
        try:
            while True:
                rows = cur.fetchmany(chunksize)
                if not rows:
                    break
                chunk = pd.DataFrame.from_records(rows, columns=col_names)
                chunk = normalize_dataframe(chunk, columns)
                chunk_meta = columns
                if col_names != [c.name for c in columns]:
                    by_name = {c.name: c for c in columns}
                    chunk_meta = [
                        by_name.get(
                            name,
                            ColumnMeta(name, "nvarchar", -1, None, None, True),
                        )
                        for name in col_names
                    ]
                    arrow_schema = build_arrow_schema(chunk_meta)

                if parquet_path is not None:
                    arrow_table = dataframe_to_arrow(chunk, arrow_schema)
                    if locked_schema is None:
                        locked_schema = pa.schema(
                            [
                                pa.field(f.name, f.type, nullable=True)
                                for f in arrow_table.schema
                            ]
                        )
                        arrow_table = arrow_table.cast(locked_schema)
                        writer = pq.ParquetWriter(parquet_path, locked_schema)
                    else:
                        arrow_table = arrow_table.cast(locked_schema)
                    writer.write_table(arrow_table)

                if csv_path is not None:
                    write_csv_chunk(chunk, csv_path, header=csv_header)
                    csv_header = False

                written += len(chunk)
        finally:
            if writer is not None:
                writer.close()
            cur.close()

        if written == 0:
            if parquet_path is not None:
                write_empty_parquet(parquet_path, columns or col_names)
            if csv_path is not None:
                write_empty_csv(csv_path, columns or col_names)

        if row_count is not None and written != row_count:
            print(
                f"  !! rowcount mismatch sql={row_count} written={written}",
                flush=True,
            )

        return TableResult(
            schema=schema,
            table=table,
            row_count=written if row_count is None else row_count,
            output_path=str(parquet_path) if parquet_path else str(csv_path),
            status="ok",
            seconds=round(time.time() - started, 3),
            csv_path=str(csv_path) if csv_path else None,
        )
    except Exception as exc:  # noqa: BLE001 - capture per-table failures
        message = str(exc)
        for path in (parquet_path, csv_path):
            if path is not None and path.exists():
                path.unlink(missing_ok=True)
        sidecar_base = parquet_path or csv_path
        if sidecar_base is not None:
            write_error_sidecar(sidecar_base, message)
        return TableResult(
            schema=schema,
            table=table,
            row_count=row_count,
            output_path=None,
            status="error",
            error=message,
            seconds=round(time.time() - started, 3),
        )


def write_manifest(out_dir: Path, results: list[TableResult]) -> None:
    manifest_json = out_dir / "export_manifest.json"
    manifest_csv = out_dir / "export_manifest.csv"
    payload = [asdict(r) for r in results]
    manifest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with manifest_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "schema",
                "table",
                "row_count",
                "output_path",
                "csv_path",
                "status",
                "error",
                "seconds",
            ],
        )
        writer.writeheader()
        writer.writerows(payload)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    include_schemas = split_csv(args.schemas)
    exclude_schemas = split_csv(args.exclude_schemas)
    include_tables = {
        tuple(part.split(".", 1))
        for part in split_csv(args.tables)
        if "." in part
    }

    print(
        f"[export] connecting to {args.host}:{args.port}/{args.database}",
        flush=True,
    )
    conn = connect(args)
    tables = list_tables(conn, include_schemas, exclude_schemas)
    if include_tables:
        tables = [(s, t) for s, t in tables if (s, t) in include_tables]
        missing = include_tables - set(tables)
        if missing:
            print(f"[export] warning: tables not found: {sorted(missing)}", flush=True)
    formats = parse_formats(args.format)
    print(
        f"[export] found {len(tables)} tables to export (format={args.format})",
        flush=True,
    )

    results: list[TableResult] = []
    failures = 0

    for idx, (schema, table) in enumerate(tables, start=1):
        stem = Path("tables") / safe_path_part(schema) / safe_path_part(table)
        parquet_path = (out_dir / stem).with_suffix(".parquet") if "parquet" in formats else None
        csv_path = (out_dir / stem).with_suffix(".csv") if "csv" in formats else None
        print(f"[export] ({idx}/{len(tables)}) {schema}.{table}", flush=True)

        parquet_ready = parquet_path is None or parquet_path.exists()
        csv_ready = csv_path is None or csv_path.exists()
        if parquet_ready and csv_ready and not args.force:
            results.append(
                TableResult(
                    schema=schema,
                    table=table,
                    row_count=None,
                    output_path=str(parquet_path) if parquet_path else str(csv_path),
                    status="skipped_exists",
                    csv_path=str(csv_path) if csv_path else None,
                )
            )
            print("  -> skipped (exists)", flush=True)
            continue

        result = export_table(
            conn, schema, table, parquet_path, csv_path, args.chunksize
        )
        results.append(result)
        if result.status.startswith("ok"):
            print(
                f"  -> {result.status} rows={result.row_count} in {result.seconds}s",
                flush=True,
            )
        else:
            failures += 1
            print(f"  -> ERROR: {result.error}", flush=True)
            if args.fail_fast:
                break

    write_manifest(out_dir, results)
    if not args.skip_docs:
        row_counts = {(r.schema, r.table): r.row_count for r in results}
        try:
            write_legacy_docs(conn, out_dir, args.database, row_counts)
        except Exception as exc:  # noqa: BLE001 - docs must not fail the extract
            print(f"[docs] ERROR writing catalog (table export is still valid): {exc}", flush=True)
    ok = sum(1 for r in results if r.status.startswith("ok"))
    skipped = sum(1 for r in results if r.status.startswith("skipped"))
    print(
        f"[export] done. ok={ok} skipped={skipped} failed={failures} "
        f"manifest={out_dir / 'export_manifest.json'}",
        flush=True,
    )
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr, flush=True)
        sys.exit(130)
