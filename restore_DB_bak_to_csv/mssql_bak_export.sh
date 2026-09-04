#!/usr/bin/env bash
# Format-neutral name for the SQL Server .bak exporter.
# Same tool as mssql_bak_to_parquet.sh; pick output with --format parquet|csv|both.
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mssql_bak_to_parquet.sh" "$@"
