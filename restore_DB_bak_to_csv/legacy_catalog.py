"""Build a readable legacy-database guide from SQL Server catalog metadata.

Writes:
  legacy_database.md   — how to navigate the dump (populated tables + FKs)
  er_diagram.md        — Mermaid ER diagrams, one block per relationship cluster
  schema_catalog.json  — machine-readable PK/FK/column inventory
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pyodbc

SAFE_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
MAX_ENTITIES_PER_DIAGRAM = 40


@dataclass(frozen=True)
class TableKey:
    schema: str
    table: str

    @property
    def fq(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def mermaid(self) -> str:
        raw = f"{self.schema}_{self.table}"
        cleaned = SAFE_IDENT_RE.sub("_", raw).strip("_")
        if cleaned and cleaned[0].isdigit():
            cleaned = f"t_{cleaned}"
        return cleaned or "unnamed"


@dataclass
class ColumnInfo:
    name: str
    type_name: str
    max_length: int | None
    precision: int | None
    scale: int | None
    is_nullable: bool
    is_pk: bool = False
    fk_to: str | None = None


@dataclass
class ForeignKey:
    name: str
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str

    @property
    def from_key(self) -> TableKey:
        return TableKey(self.from_schema, self.from_table)

    @property
    def to_key(self) -> TableKey:
        return TableKey(self.to_schema, self.to_table)


def _quote(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def fetch_columns(conn: pyodbc.Connection) -> dict[TableKey, list[ColumnInfo]]:
    sql = """
    SELECT
        s.name AS schema_name,
        t.name AS table_name,
        c.name AS column_name,
        ty.name AS type_name,
        c.max_length,
        c.precision,
        c.scale,
        c.is_nullable
    FROM sys.columns AS c
    INNER JOIN sys.tables AS t ON t.object_id = c.object_id
    INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    INNER JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
    WHERE t.is_ms_shipped = 0
    ORDER BY s.name, t.name, c.column_id
    """
    out: dict[TableKey, list[ColumnInfo]] = defaultdict(list)
    cur = conn.cursor()
    cur.execute(sql)
    for schema, table, name, type_name, max_length, precision, scale, is_nullable in cur.fetchall():
        out[TableKey(schema, table)].append(
            ColumnInfo(
                name=name,
                type_name=str(type_name).lower(),
                max_length=int(max_length) if max_length is not None else None,
                precision=int(precision) if precision is not None else None,
                scale=int(scale) if scale is not None else None,
                is_nullable=bool(is_nullable),
            )
        )
    return dict(out)


def fetch_primary_keys(conn: pyodbc.Connection) -> dict[TableKey, list[str]]:
    sql = """
    SELECT
        s.name AS schema_name,
        t.name AS table_name,
        c.name AS column_name,
        ic.key_ordinal
    FROM sys.indexes AS i
    INNER JOIN sys.index_columns AS ic
        ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    INNER JOIN sys.columns AS c
        ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    INNER JOIN sys.tables AS t ON t.object_id = i.object_id
    INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    WHERE i.is_primary_key = 1 AND t.is_ms_shipped = 0
    ORDER BY s.name, t.name, ic.key_ordinal
    """
    out: dict[TableKey, list[str]] = defaultdict(list)
    cur = conn.cursor()
    cur.execute(sql)
    for schema, table, column, _ordinal in cur.fetchall():
        out[TableKey(schema, table)].append(column)
    return dict(out)


def fetch_foreign_keys(conn: pyodbc.Connection) -> list[ForeignKey]:
    sql = """
    SELECT
        fk.name AS fk_name,
        sch_from.name AS from_schema,
        tab_from.name AS from_table,
        col_from.name AS from_column,
        sch_to.name AS to_schema,
        tab_to.name AS to_table,
        col_to.name AS to_column
    FROM sys.foreign_keys AS fk
    INNER JOIN sys.foreign_key_columns AS fkc
        ON fkc.constraint_object_id = fk.object_id
    INNER JOIN sys.tables AS tab_from ON tab_from.object_id = fkc.parent_object_id
    INNER JOIN sys.schemas AS sch_from ON sch_from.schema_id = tab_from.schema_id
    INNER JOIN sys.columns AS col_from
        ON col_from.object_id = fkc.parent_object_id
       AND col_from.column_id = fkc.parent_column_id
    INNER JOIN sys.tables AS tab_to ON tab_to.object_id = fkc.referenced_object_id
    INNER JOIN sys.schemas AS sch_to ON sch_to.schema_id = tab_to.schema_id
    INNER JOIN sys.columns AS col_to
        ON col_to.object_id = fkc.referenced_object_id
       AND col_to.column_id = fkc.referenced_column_id
    WHERE tab_from.is_ms_shipped = 0 AND tab_to.is_ms_shipped = 0
    ORDER BY sch_from.name, tab_from.name, fk.name, fkc.constraint_column_id
    """
    cur = conn.cursor()
    cur.execute(sql)
    return [
        ForeignKey(
            name=name,
            from_schema=from_schema,
            from_table=from_table,
            from_column=from_column,
            to_schema=to_schema,
            to_table=to_table,
            to_column=to_column,
        )
        for name, from_schema, from_table, from_column, to_schema, to_table, to_column in cur.fetchall()
    ]


def fetch_partition_row_counts(conn: pyodbc.Connection) -> dict[TableKey, int]:
    """Approximate counts from partition stats (fast; good enough for docs)."""
    sql = """
    SELECT s.name, t.name, SUM(p.row_count)
    FROM sys.tables AS t
    INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    INNER JOIN sys.dm_db_partition_stats AS p ON p.object_id = t.object_id
    WHERE t.is_ms_shipped = 0 AND p.index_id IN (0, 1)
    GROUP BY s.name, t.name
    """
    out: dict[TableKey, int] = {}
    cur = conn.cursor()
    cur.execute(sql)
    for schema, table, n in cur.fetchall():
        out[TableKey(schema, table)] = int(n or 0)
    return out


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _sql_type(col: ColumnInfo) -> str:
    t = col.type_name
    if t in {"decimal", "numeric"} and col.precision is not None:
        return f"{t}({col.precision},{col.scale or 0})"
    if t in {"nvarchar", "varchar", "nchar", "char", "varbinary", "binary"}:
        if col.max_length == -1:
            return f"{t}(max)"
        if col.max_length is not None:
            chars = col.max_length // 2 if t.startswith("n") else col.max_length
            return f"{t}({chars})"
    return t


def _mermaid_type(col: ColumnInfo) -> str:
    t = col.type_name
    if t in {"bigint", "int", "smallint", "tinyint", "bit"}:
        return "int"
    if t in {"decimal", "numeric", "money", "smallmoney", "float", "real"}:
        return "float"
    if t in {"date", "datetime", "datetime2", "smalldatetime", "time", "datetimeoffset"}:
        return "datetime"
    return "string"


def _annotate_columns(
    columns: dict[TableKey, list[ColumnInfo]],
    pks: dict[TableKey, list[str]],
    fks: list[ForeignKey],
) -> None:
    fk_map: dict[tuple[str, str, str], str] = {}
    for fk in fks:
        fk_map[(fk.from_schema, fk.from_table, fk.from_column)] = (
            f"{fk.to_schema}.{fk.to_table}.{fk.to_column}"
        )
    for key, cols in columns.items():
        pk_set = set(pks.get(key, []))
        for col in cols:
            col.is_pk = col.name in pk_set
            col.fk_to = fk_map.get((key.schema, key.table, col.name))


def _connected_components(
    tables: Iterable[TableKey], fks: list[ForeignKey]
) -> list[list[TableKey]]:
    keys = list(tables)
    parent: dict[TableKey, TableKey] = {k: k for k in keys}

    def find(x: TableKey) -> TableKey:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: TableKey, b: TableKey) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    known = set(keys)
    for fk in fks:
        if fk.from_key in known and fk.to_key in known:
            union(fk.from_key, fk.to_key)

    groups: dict[TableKey, list[TableKey]] = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    components = [sorted(v, key=lambda t: t.fq) for v in groups.values()]
    components.sort(key=lambda g: (-len(g), g[0].fq))
    return components


def _active_tables(
    row_counts: dict[TableKey, int],
    fks: list[ForeignKey],
) -> set[TableKey]:
    populated = {k for k, n in row_counts.items() if n > 0}
    active = set(populated)
    # Keep empty lookup tables that populated tables actually reference.
    changed = True
    while changed:
        changed = False
        for fk in fks:
            if fk.from_key in active and fk.to_key not in active:
                active.add(fk.to_key)
                changed = True
            if fk.to_key in active and fk.from_key not in active and row_counts.get(fk.from_key, 0) > 0:
                active.add(fk.from_key)
                changed = True
    return active


def _render_mermaid(
    tables: list[TableKey],
    columns: dict[TableKey, list[ColumnInfo]],
    fks: list[ForeignKey],
    include_columns: bool,
) -> str:
    wanted = set(tables)
    lines = ["erDiagram"]
    if include_columns:
        for key in tables:
            attrs = []
            for col in columns.get(key, []):
                flags = []
                if col.is_pk:
                    flags.append("PK")
                if col.fk_to:
                    flags.append("FK")
                flag_s = " ".join(flags)
                attr_name = SAFE_IDENT_RE.sub("_", col.name) or "col"
                if flag_s:
                    attrs.append(f"    {_mermaid_type(col)} {attr_name} {flag_s}")
                else:
                    attrs.append(f"    {_mermaid_type(col)} {attr_name}")
            body = "\n".join(attrs)
            lines.append(f"  {key.mermaid} {{\n{body}\n  }}")
    else:
        for key in tables:
            lines.append(f"  {key.mermaid} {{")
            lines.append("    string table")
            lines.append("  }")

    seen: set[tuple[str, str, str]] = set()
    for fk in fks:
        if fk.from_key not in wanted or fk.to_key not in wanted:
            continue
        edge = (fk.from_key.mermaid, fk.to_key.mermaid, fk.from_column)
        if edge in seen:
            continue
        seen.add(edge)
        label = SAFE_IDENT_RE.sub("_", fk.from_column) or "fk"
        lines.append(
            f"  {fk.from_key.mermaid} }}o--|| {fk.to_key.mermaid} : {label}"
        )
    return "\n".join(lines)


def write_legacy_docs(
    conn: pyodbc.Connection,
    out_dir: Path,
    database: str,
    row_counts: dict[tuple[str, str], int | None] | None = None,
) -> None:
    print("[docs] reading SQL Server catalog (tables, columns, PK, FK)...", flush=True)
    columns = fetch_columns(conn)
    pks = fetch_primary_keys(conn)
    fks = fetch_foreign_keys(conn)
    approx = fetch_partition_row_counts(conn)

    counts: dict[TableKey, int] = dict(approx)
    if row_counts:
        for (schema, table), n in row_counts.items():
            if n is not None:
                counts[TableKey(schema, table)] = int(n)

    _annotate_columns(columns, pks, fks)

    all_tables = sorted(columns.keys(), key=lambda t: t.fq)
    populated = [t for t in all_tables if counts.get(t, 0) > 0]
    empty = [t for t in all_tables if counts.get(t, 0) <= 0]
    active = _active_tables(counts, fks)
    er_tables = [t for t in all_tables if t in active]
    components = _connected_components(er_tables, fks) if er_tables else []

    catalog = {
        "database": database,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "table_count": len(all_tables),
        "populated_tables": len(populated),
        "empty_tables": len(empty),
        "foreign_key_count": len(fks),
        "tables": [
            {
                "schema": t.schema,
                "table": t.table,
                "row_count": counts.get(t, 0),
                "primary_key": pks.get(t, []),
                "columns": [asdict(c) for c in columns[t]],
            }
            for t in all_tables
        ],
        "foreign_keys": [asdict(fk) for fk in fks],
    }
    (out_dir / "schema_catalog.json").write_text(
        json.dumps(catalog, indent=2), encoding="utf-8"
    )

    er_md = _build_er_markdown(database, components, columns, fks, counts)
    (out_dir / "er_diagram.md").write_text(er_md, encoding="utf-8")

    guide = _build_guide_markdown(
        database=database,
        all_tables=all_tables,
        populated=populated,
        empty=empty,
        columns=columns,
        pks=pks,
        fks=fks,
        counts=counts,
        components=components,
    )
    (out_dir / "legacy_database.md").write_text(guide, encoding="utf-8")
    print(
        f"[docs] wrote {out_dir / 'legacy_database.md'} "
        f"and {out_dir / 'er_diagram.md'} "
        f"(populated={len(populated)} empty={len(empty)} fks={len(fks)})",
        flush=True,
    )


def _build_er_markdown(
    database: str,
    components: list[list[TableKey]],
    columns: dict[TableKey, list[ColumnInfo]],
    fks: list[ForeignKey],
    counts: dict[TableKey, int],
) -> str:
    lines = [
        f"# ER diagram — `{database}`",
        "",
        "Generated from declared SQL Server foreign keys. Isolated tables with no FKs are omitted.",
        "Empty lookup tables appear only when a populated table references them.",
        "",
        "Open this file in GitHub, Azure DevOps, or any Mermaid preview to render the diagrams.",
        "",
    ]
    if not components:
        lines.append("No foreign keys were declared in this database.")
        lines.append("")
        return "\n".join(lines)

    for i, group in enumerate(components, start=1):
        if len(group) == 1:
            key = group[0]
            has_fk = any(fk.from_key == key or fk.to_key == key for fk in fks)
            if not has_fk:
                continue
        names = ", ".join(f"`{t.fq}`" for t in group[:12])
        extra = "" if len(group) <= 12 else f" (+{len(group) - 12} more)"
        diagram_tables = group
        include_cols = len(group) <= 12
        if len(group) > MAX_ENTITIES_PER_DIAGRAM:
            ranked = sorted(group, key=lambda t: counts.get(t, 0), reverse=True)
            core = set(ranked[:20])
            for fk in fks:
                if fk.from_key in core and fk.to_key in group:
                    core.add(fk.to_key)
                if fk.to_key in core and fk.from_key in group:
                    core.add(fk.from_key)
            diagram_tables = sorted(core, key=lambda t: (-counts.get(t, 0), t.fq))[
                :MAX_ENTITIES_PER_DIAGRAM
            ]
            include_cols = False
        lines.append(f"## Cluster {i} — {len(group)} tables")
        lines.append("")
        lines.append(f"Tables: {names}{extra}")
        lines.append("")
        if diagram_tables != group:
            lines.append(
                f"Mermaid shows the {len(diagram_tables)} busiest tables plus their FK neighbors "
                f"(full cluster is {len(group)} tables — Mermaid gets unreadable past ~{MAX_ENTITIES_PER_DIAGRAM})."
            )
            lines.append("")
        lines.append("| Table | Rows |")
        lines.append("| --- | ---: |")
        for t in group:
            lines.append(f"| `{t.fq}` | {counts.get(t, 0):,} |")
        lines.append("")
        mermaid = _render_mermaid(diagram_tables, columns, fks, include_columns=include_cols)
        lines.append("```mermaid")
        lines.append(mermaid)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _build_guide_markdown(
    database: str,
    all_tables: list[TableKey],
    populated: list[TableKey],
    empty: list[TableKey],
    columns: dict[TableKey, list[ColumnInfo]],
    pks: dict[TableKey, list[str]],
    fks: list[ForeignKey],
    counts: dict[TableKey, int],
    components: list[list[TableKey]],
) -> str:
    total_rows = sum(counts.get(t, 0) for t in all_tables)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Legacy database guide — `{database}`",
        "",
        f"Generated {generated} from the SQL Server catalog (not from guessing column names).",
        "",
        "## How to read this dump",
        "",
        "1. **Trust row counts first.** Empty tables are unused modules, not missing extracts.",
        "2. **Follow foreign keys**, not table-name guesses. Civic/Springbrook names are often cryptic.",
        "3. **Start from populated hubs** (largest tables below), then walk outbound FKs to lookups.",
        "4. Open [`er_diagram.md`](er_diagram.md) for Mermaid relationship clusters.",
        "5. Use [`schema_catalog.json`](schema_catalog.json) if you need this metadata in a script.",
        "",
        "## Snapshot",
        "",
        f"- Database: `{database}`",
        f"- User tables: **{len(all_tables)}**",
        f"- Tables with rows: **{len(populated)}**",
        f"- Empty tables: **{len(empty)}**",
        f"- Declared foreign keys: **{len(fks)}**",
        f"- Approximate total rows: **{total_rows:,}**",
        "",
        "## Largest tables",
        "",
        "| Rank | Table | Rows | PK | Outbound FKs | Inbound FKs |",
        "| ---: | --- | ---: | --- | ---: | ---: |",
    ]

    outbound = defaultdict(int)
    inbound = defaultdict(int)
    for fk in fks:
        outbound[fk.from_key] += 1
        inbound[fk.to_key] += 1

    ranked = sorted(populated, key=lambda t: counts.get(t, 0), reverse=True)
    for i, t in enumerate(ranked[:25], start=1):
        pk = ", ".join(f"`{c}`" for c in pks.get(t, [])) or "—"
        lines.append(
            f"| {i} | `{t.fq}` | {counts.get(t, 0):,} | {pk} | "
            f"{outbound.get(t, 0)} | {inbound.get(t, 0)} |"
        )
    lines.extend(["", "## Relationship clusters", ""])
    if not any(len(g) > 1 or _has_fk(g[0], fks) for g in components if g):
        lines.append("No declared foreign keys. Infer joins from column names only as a last resort.")
        lines.append("")
    else:
        lines.append("Each cluster is a set of tables connected by declared FKs. See `er_diagram.md` to render them.")
        lines.append("")
        lines.append("| Cluster | Tables | Populated |")
        lines.append("| ---: | ---: | ---: |")
        cluster_n = 0
        for group in components:
            if len(group) == 1 and not _has_fk(group[0], fks):
                continue
            cluster_n += 1
            pop = sum(1 for t in group if counts.get(t, 0) > 0)
            lines.append(f"| {cluster_n} | {len(group)} | {pop} |")
        lines.append("")

    lines.extend(
        [
            "## Tables with data",
            "",
            "Column lists are only written for populated tables. That is the working set for migration.",
            "",
        ]
    )
    for t in ranked:
        pk_cols = pks.get(t, [])
        lines.append(f"### `{t.fq}` — {counts.get(t, 0):,} rows")
        lines.append("")
        if pk_cols:
            lines.append("Primary key: " + ", ".join(f"`{c}`" for c in pk_cols))
            lines.append("")
        child_fks = [fk for fk in fks if fk.from_key == t]
        parent_fks = [fk for fk in fks if fk.to_key == t]
        if child_fks:
            lines.append("References:")
            for fk in child_fks:
                lines.append(
                    f"- `{fk.from_column}` → `{fk.to_key.fq}.{fk.to_column}`"
                )
            lines.append("")
        if parent_fks:
            lines.append("Referenced by:")
            seen_from: set[str] = set()
            for fk in parent_fks:
                label = fk.from_key.fq
                if label in seen_from:
                    continue
                seen_from.add(label)
                n = counts.get(fk.from_key, 0)
                lines.append(f"- `{label}` ({n:,} rows)")
            lines.append("")
        lines.append("| Column | Type | Nullable | Keys |")
        lines.append("| --- | --- | --- | --- |")
        for col in columns[t]:
            keys = []
            if col.is_pk:
                keys.append("PK")
            if col.fk_to:
                keys.append(f"FK → `{col.fk_to}`")
            lines.append(
                f"| `{_md_cell(col.name)}` | `{_sql_type(col)}` | "
                f"{'yes' if col.is_nullable else 'no'} | {_md_cell(' '.join(keys) or '—')} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Empty tables",
            "",
            "These restored successfully but have zero rows. Treat them as unused product modules unless business says otherwise.",
            "",
            "| Table | Columns | PK |",
            "| --- | ---: | --- |",
        ]
    )
    for t in empty:
        pk = ", ".join(f"`{c}`" for c in pks.get(t, [])) or "—"
        lines.append(f"| `{t.fq}` | {len(columns.get(t, []))} | {pk} |")
    lines.append("")
    return "\n".join(lines)


def _has_fk(key: TableKey, fks: list[ForeignKey]) -> bool:
    return any(fk.from_key == key or fk.to_key == key for fk in fks)
