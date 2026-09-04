#!/usr/bin/env bash
# Restore any SQL Server .bak in Docker and export all user tables to Parquet and/or CSV.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_NAME="mssql_bak_to_parquet"

BAK_PATH=""
POSITIONAL_BAK=""
OUT_DIR=""
SA_PASSWORD="${MSSQL_SA_PASSWORD:-BakExport!Pass123}"
CONTAINER_NAME="${MSSQL_CONTAINER_NAME:-mssql_bak_restore}"
NETWORK_NAME="${MSSQL_NETWORK_NAME:-mssql_bak_net}"
MSSQL_IMAGE="${MSSQL_IMAGE:-mcr.microsoft.com/mssql/server:2022-latest}"
EXPORTER_IMAGE="${EXPORTER_IMAGE:-mssql-bak-parquet-exporter:latest}"
MSSQL_PLATFORM="${MSSQL_PLATFORM:-linux/amd64}"
HOST_PORT="${MSSQL_HOST_PORT:-1433}"
KEEP_SQLSERVER=0
SKIP_RESTORE=0
SKIP_EXPORT=0
SKIP_DOCS=0
FORCE_EXPORT=0
REBUILD_EXPORTER=0
FAIL_FAST=0
SCHEMAS=""
TABLES=""
FORMAT="parquet"
CHUNKSIZE=50000

usage() {
  cat <<EOF
Usage:
  $(basename "$0") --bak /path/to/backup.bak [--format parquet|csv|both] [options]
  $(basename "$0") /path/to/backup.bak [--format parquet|csv|both] [options]

Required:
  --bak PATH              SQL Server .bak file (or pass the path as the first argument)

Options:
  --out PATH              Output directory (default: ./<bak-stem>_export)
  --format FORMAT         parquet | csv | both (default: parquet)
  --sa-password PASS      SA password (default: env MSSQL_SA_PASSWORD or built-in)
  --container-name NAME   SQL Server container name (default: ${CONTAINER_NAME})
  --network-name NAME     Docker network name (default: ${NETWORK_NAME})
  --mssql-image IMAGE     SQL Server image (default: ${MSSQL_IMAGE})
  --host-port PORT        Host port mapped to 1433 (default: ${HOST_PORT})
  --schemas LIST          Comma-separated schema allow-list (default: all)
  --tables LIST           Comma-separated schema.table allow-list (default: all)
  --chunksize N           Export chunk size (default: ${CHUNKSIZE})
  --keep-sqlserver        Keep SQL Server container + data volume after export
  --skip-restore          Reuse an already-restored database (requires --keep-sqlserver)
  --skip-export           Only restore; do not export tables
  --skip-docs             Skip ER diagram and legacy_database.md
  --force                 Re-export tables even if output files already exist
  --fail-fast             Stop on the first table export failure
  --rebuild-exporter      Rebuild exporter image with --no-cache
  -h, --help              Show this help

Examples:
  $(basename "$0") ./source_data/mu1427.bak --format csv
  $(basename "$0") --bak ./source_data/mu1427.bak --format both --out ./output/export
  $(basename "$0") --bak /data/erp.bak --out /data/parquet --schemas dbo,payroll --keep-sqlserver
EOF
}

log() { printf '[%s] %s\n' "${TOOL_NAME}" "$*"; }
err() { printf '[%s] ERROR: %s\n' "${TOOL_NAME}" "$*" >&2; }
die() { err "$*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bak) BAK_PATH="${2:-}"; shift 2 ;;
    --out) OUT_DIR="${2:-}"; shift 2 ;;
    --sa-password) SA_PASSWORD="${2:-}"; shift 2 ;;
    --container-name) CONTAINER_NAME="${2:-}"; shift 2 ;;
    --network-name) NETWORK_NAME="${2:-}"; shift 2 ;;
    --mssql-image) MSSQL_IMAGE="${2:-}"; shift 2 ;;
    --host-port) HOST_PORT="${2:-}"; shift 2 ;;
    --schemas) SCHEMAS="${2:-}"; shift 2 ;;
    --tables) TABLES="${2:-}"; shift 2 ;;
    --format) FORMAT="${2:-}"; shift 2 ;;
    --chunksize) CHUNKSIZE="${2:-}"; shift 2 ;;
    --keep-sqlserver) KEEP_SQLSERVER=1; shift ;;
    --skip-restore) SKIP_RESTORE=1; shift ;;
    --skip-export) SKIP_EXPORT=1; shift ;;
    --skip-docs) SKIP_DOCS=1; shift ;;
    --force) FORCE_EXPORT=1; shift ;;
    --fail-fast) FAIL_FAST=1; shift ;;
    --rebuild-exporter) REBUILD_EXPORTER=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "Unknown argument: $1" ;;
    *)
      if [[ -z "${POSITIONAL_BAK}" ]]; then
        POSITIONAL_BAK="$1"
        shift
      else
        die "Unexpected extra argument: $1"
      fi
      ;;
  esac
done

if [[ -z "${BAK_PATH}" && -n "${POSITIONAL_BAK}" ]]; then
  BAK_PATH="${POSITIONAL_BAK}"
elif [[ -n "${BAK_PATH}" && -n "${POSITIONAL_BAK}" ]]; then
  die "Pass the backup as --bak PATH or as a positional path, not both"
fi
[[ -n "${BAK_PATH}" ]] || { usage; die "--bak is required (or pass the .bak path as the first argument)"; }
[[ -f "${BAK_PATH}" ]] || die "Backup file not found: ${BAK_PATH}"
case "${FORMAT}" in
  parquet|csv|both) ;;
  *) die "--format must be parquet, csv, or both (got: ${FORMAT})" ;;
esac
if [[ "${BAK_PATH}" != *.bak && "${BAK_PATH}" != *.BAK ]]; then
  log "Warning: backup path does not end with .bak: ${BAK_PATH}"
fi

BAK_PATH="$(cd "$(dirname "${BAK_PATH}")" && pwd)/$(basename "${BAK_PATH}")"
BAK_DIR="$(dirname "${BAK_PATH}")"
BAK_FILE="$(basename "${BAK_PATH}")"
VOLUME_NAME="${CONTAINER_NAME}_data"
if [[ -z "${OUT_DIR}" ]]; then
  local_stem="${BAK_FILE%.*}"
  OUT_DIR="$(pwd)/${local_stem}_export"
fi
mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"
WORK_DIR="${OUT_DIR}/.work"
mkdir -p "${WORK_DIR}"

bytes_to_gb() {
  local bytes="$1"
  awk -v b="${bytes}" 'BEGIN { printf "%.1f", b / 1024 / 1024 / 1024 }'
}

check_docker() {
  log "Checking Docker runtime..."
  command -v docker >/dev/null 2>&1 || die "Docker CLI not found. Install Docker Desktop (see README.md)."

  if ! docker info >/dev/null 2>&1; then
    die "Docker daemon is not running. Start Docker Desktop, wait until it is healthy, then retry."
  fi

  local server_version
  server_version="$(docker info --format '{{.ServerVersion}}' 2>/dev/null || true)"
  [[ -n "${server_version}" ]] || die "Could not read Docker server version."
  log "Docker is running (engine ${server_version})"
}

warn_disk_space() {
  local bak_bytes avail_bytes
  bak_bytes="$(wc -c < "${BAK_PATH}" | tr -d ' ')"
  avail_bytes="$(df -P "${OUT_DIR}" | awk 'NR==2 {print $4 * 1024}')"

  local bak_gb avail_gb
  bak_gb="$(bytes_to_gb "${bak_bytes}")"
  avail_gb="$(bytes_to_gb "${avail_bytes}")"

  log "Backup size: ${bak_gb} GiB | free space on output volume: ${avail_gb} GiB"
  # Restore files + parquet often need ~2-3x bak size in practice.
  local recommend
  recommend="$(awk -v b="${bak_bytes}" 'BEGIN { printf "%.0f", (b * 3) / 1024 / 1024 / 1024 }')"
  if awk -v a="${avail_bytes}" -v b="${bak_bytes}" 'BEGIN { exit !(a < b * 2) }'; then
    err "Low disk space. Recommend ~${recommend} GiB free for restore + parquet export."
    err "Also increase Docker Desktop -> Settings -> Resources -> Virtual disk limit."
  fi
}

ensure_network() {
  if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    log "Creating Docker network ${NETWORK_NAME}"
    docker network create "${NETWORK_NAME}" >/dev/null
  fi
}

sqlcmd_in_container() {
  # Detect tools path across mssql image variants.
  local sqlcmd_path
  sqlcmd_path="$(docker exec "${CONTAINER_NAME}" bash -lc \
    'if [ -x /opt/mssql-tools18/bin/sqlcmd ]; then echo /opt/mssql-tools18/bin/sqlcmd;
     elif [ -x /opt/mssql-tools/bin/sqlcmd ]; then echo /opt/mssql-tools/bin/sqlcmd;
     else exit 1; fi')"

  docker exec \
    -e SQLCMDPASSWORD="${SA_PASSWORD}" \
    "${CONTAINER_NAME}" \
    "${sqlcmd_path}" -S localhost -U sa -C -b "$@"
}

wait_for_sqlserver() {
  log "Waiting for SQL Server to accept connections..."
  local i
  for i in $(seq 1 90); do
    if sqlcmd_in_container -Q "SELECT 1" >/dev/null 2>&1; then
      log "SQL Server is ready"
      return 0
    fi
    sleep 2
  done
  die "SQL Server did not become ready in time. Check: docker logs ${CONTAINER_NAME}"
}

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"
}

container_running() {
  [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo false)" == "true" ]]
}

bak_visible_in_container() {
  docker exec "${CONTAINER_NAME}" test -f "/backup/${BAK_FILE}" >/dev/null 2>&1
}

create_sqlserver_container() {
  log "Pulling ${MSSQL_IMAGE} (${MSSQL_PLATFORM}) if needed..."
  docker pull --platform "${MSSQL_PLATFORM}" "${MSSQL_IMAGE}" \
    || die "docker pull failed for ${MSSQL_IMAGE}"
  log "Starting SQL Server container (${MSSQL_IMAGE}, platform ${MSSQL_PLATFORM})"
  # linux/amd64 is required for official SQL Server images (including Apple Silicon via emulation).
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --hostname "${CONTAINER_NAME}" \
    --platform "${MSSQL_PLATFORM}" \
    --network "${NETWORK_NAME}" \
    -e ACCEPT_EULA=Y \
    -e MSSQL_SA_PASSWORD="${SA_PASSWORD}" \
    -e MSSQL_PID=Developer \
    -p "${HOST_PORT}:1433" \
    -v "${BAK_DIR}:/backup:ro" \
    -v "${VOLUME_NAME}:/var/opt/mssql" \
    "${MSSQL_IMAGE}" >/dev/null
}

start_sqlserver() {
  local recreate=0
  if container_exists; then
    if container_running; then
      if bak_visible_in_container; then
        log "Reusing running container ${CONTAINER_NAME}"
        wait_for_sqlserver
        return 0
      else
        log "Backup not visible in container; recreating to remount ${BAK_DIR}"
        recreate=1
      fi
    else
      log "Starting existing container ${CONTAINER_NAME}"
      docker start "${CONTAINER_NAME}" >/dev/null
      wait_for_sqlserver
      if bak_visible_in_container; then
        return 0
      fi
      log "Backup not visible after start; recreating to remount ${BAK_DIR}"
      recreate=1
    fi
  else
    create_sqlserver_container
    wait_for_sqlserver
    bak_visible_in_container || die "Backup is not visible inside the container at /backup/${BAK_FILE}."
    return 0
  fi

  if [[ "${recreate}" -eq 1 ]]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null || true
    create_sqlserver_container
    wait_for_sqlserver
    bak_visible_in_container || die "Backup is not visible inside the container at /backup/${BAK_FILE}."
  fi
}

run_sql_file() {
  local sql_file="$1"
  sqlcmd_in_container -i "${sql_file}"
}

restore_backup() {
  local bak_in_container="/backup/${BAK_FILE}"
  local header_file="${WORK_DIR}/header.txt"
  local files_file="${WORK_DIR}/filelist.txt"
  local restore_sql="${WORK_DIR}/restore.sql"
  local db_name_file="${WORK_DIR}/dbname.txt"

  log "Reading backup header..."
  sqlcmd_in_container -s"|" -W -Q \
    "SET NOCOUNT ON; RESTORE HEADERONLY FROM DISK = N'${bak_in_container}'" \
    > "${header_file}"

  # HEADERONLY columns vary slightly; DatabaseName is usually column 2 (index 1 in 0-based after split).
  local db_name
  db_name="$(awk -F'|' '
    NR==1 {
      for (i=1; i<=NF; i++) {
        gsub(/^[ \t]+|[ \t]+$/, "", $i)
        if ($i == "DatabaseName") col=i
      }
      next
    }
    col && $0 !~ /^[-| ]+$/ && $0 !~ /^$/ {
      gsub(/^[ \t]+|[ \t]+$/, "", $col)
      print $col
      exit
    }
  ' "${header_file}")"

  [[ -n "${db_name}" ]] || die "Could not parse DatabaseName from RESTORE HEADERONLY. See ${header_file}"
  printf '%s\n' "${db_name}" > "${db_name_file}"
  log "Database name in backup: ${db_name}"

  log "Reading backup file list..."
  sqlcmd_in_container -s"|" -W -Q \
    "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'${bak_in_container}'" \
    > "${files_file}"

  # Build WITH MOVE from LogicalName + Type (D/L/F/S...).
  local move_clauses=""
  move_clauses="$(awk -F'|' '
    NR==1 {
      for (i=1; i<=NF; i++) {
        gsub(/^[ \t]+|[ \t]+$/, "", $i)
        if ($i == "LogicalName") logical=i
        if ($i == "Type") typ=i
      }
      next
    }
    logical && typ && $0 !~ /^[-| ]+$/ && $0 !~ /^$/ {
      gsub(/^[ \t]+|[ \t]+$/, "", $logical)
      gsub(/^[ \t]+|[ \t]+$/, "", $typ)
      if ($logical == "" || $logical == "LogicalName") next
      lg=$logical
      safe=lg
      gsub(/[^A-Za-z0-9_.-]/, "_", safe)
      if ($typ == "L") {
        printf "MOVE N'\''%s'\'' TO N'\''/var/opt/mssql/data/%s.ldf'\''\n", lg, safe
      } else {
        printf "MOVE N'\''%s'\'' TO N'\''/var/opt/mssql/data/%s.mdf'\''\n", lg, safe
      }
    }
  ' "${files_file}")"

  [[ -n "${move_clauses}" ]] || die "Could not parse RESTORE FILELISTONLY. See ${files_file}"

  local with_move
  with_move="$(printf '%s\n' "${move_clauses}" | paste -sd, - | sed 's/,/, /g')"

  cat > "${restore_sql}" <<EOF
SET NOCOUNT ON;
IF DB_ID(N'${db_name}') IS NOT NULL
BEGIN
  ALTER DATABASE [${db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
END
RESTORE DATABASE [${db_name}]
FROM DISK = N'${bak_in_container}'
WITH REPLACE, RECOVERY, STATS = 5,
${with_move};
ALTER DATABASE [${db_name}] SET MULTI_USER;
EOF

  # sqlcmd -i needs the file inside the container; mount via docker cp
  docker cp "${restore_sql}" "${CONTAINER_NAME}:/tmp/restore.sql"
  log "Restoring database (this can take a long time for large backups)..."
  run_sql_file /tmp/restore.sql
  log "Restore completed: ${db_name}"
}

build_exporter_image() {
  log "Building exporter image ${EXPORTER_IMAGE} (Docker layer cache reused if sources unchanged)..."
  local build_args=(build -t "${EXPORTER_IMAGE}" "${SCRIPT_DIR}")
  if [[ "${REBUILD_EXPORTER}" -eq 1 ]]; then
    build_args=(build --no-cache -t "${EXPORTER_IMAGE}" "${SCRIPT_DIR}")
  fi
  docker "${build_args[@]}"
}

export_parquet() {
  local db_name
  if [[ -f "${WORK_DIR}/dbname.txt" ]]; then
    db_name="$(tr -d '\r\n' < "${WORK_DIR}/dbname.txt")"
  else
    # Fallback when --skip-restore: ask user-facing error unless DB can be discovered.
    die "Database name unknown. Run without --skip-restore once, or place db name in ${WORK_DIR}/dbname.txt"
  fi

  build_exporter_image

  local export_args=(
    --host "${CONTAINER_NAME}"
    --port 1433
    --database "${db_name}"
    --user sa
    --password "${SA_PASSWORD}"
    --out /out
    --chunksize "${CHUNKSIZE}"
  )
  [[ -n "${SCHEMAS}" ]] && export_args+=(--schemas "${SCHEMAS}")
  [[ -n "${TABLES}" ]] && export_args+=(--tables "${TABLES}")
  [[ "${FORCE_EXPORT}" -eq 1 ]] && export_args+=(--force)
  [[ "${FAIL_FAST}" -eq 1 ]] && export_args+=(--fail-fast)
  [[ "${SKIP_DOCS}" -eq 1 ]] && export_args+=(--skip-docs)
  export_args+=(--format "${FORMAT}")

  log "Exporting tables (${FORMAT}) under ${OUT_DIR}"
  docker run --rm \
    --network "${NETWORK_NAME}" \
    -v "${OUT_DIR}:/out" \
    "${EXPORTER_IMAGE}" \
    "${export_args[@]}"
}

remove_sql_resources() {
  # Container first — a volume cannot be removed while a container still mounts it.
  if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    log "Removing SQL Server container ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null || true
  fi
  if docker volume inspect "${VOLUME_NAME}" >/dev/null 2>&1; then
    log "Removing SQL data volume ${VOLUME_NAME}"
    docker volume rm "${VOLUME_NAME}" >/dev/null || true
  fi
}

remove_unused_tool_network() {
  if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    return 0
  fi
  local attached
  attached="$(docker network inspect -f '{{len .Containers}}' "${NETWORK_NAME}" 2>/dev/null || echo 1)"
  if [[ "${attached}" == "0" ]]; then
    log "Removing unused Docker network ${NETWORK_NAME}"
    docker network rm "${NETWORK_NAME}" >/dev/null || true
  fi
}

# Drop unused named volumes from earlier runs of this tool (other container names).
# In-use volumes are left alone so parallel exports stay safe.
prune_unused_tool_volumes() {
  local vol
  while IFS= read -r vol; do
    [[ -n "${vol}" ]] || continue
    [[ "${vol}" == "${VOLUME_NAME}" ]] && continue
    if [[ -n "$(docker ps -aq --filter "volume=${vol}")" ]]; then
      continue
    fi
    log "Removing leftover SQL data volume ${vol}"
    docker volume rm "${vol}" >/dev/null || true
  done < <(docker volume ls -q | grep -E '^mssql_bak_.+_data$' || true)
}

# Drop leftover SQL resources from a previous run so restore starts clean
# and Docker's virtual disk is actually freed (restored DBs are the bulk of usage).
clear_previous_run() {
  if [[ "${KEEP_SQLSERVER}" -eq 1 || "${SKIP_RESTORE}" -eq 1 ]]; then
    return 0
  fi
  log "Clearing leftover SQL Server container/volume from previous run..."
  remove_sql_resources
  prune_unused_tool_volumes
}

teardown() {
  if [[ "${KEEP_SQLSERVER}" -eq 1 ]]; then
    log "Keeping SQL Server container ${CONTAINER_NAME} and volume ${VOLUME_NAME} (--keep-sqlserver)"
    return 0
  fi
  log "Cleaning up SQL Server and Docker restore resources..."
  remove_sql_resources
  prune_unused_tool_volumes
  remove_unused_tool_network
}

cleanup_on_error() {
  local exit_code=$?
  if [[ "${exit_code}" -ne 0 ]]; then
    err "Failed with exit code ${exit_code}"
    err "Inspect logs with: docker logs ${CONTAINER_NAME}"
    err "Work files in: ${WORK_DIR}"
  fi
}
trap cleanup_on_error EXIT

main() {
  check_docker
  warn_disk_space
  clear_previous_run
  ensure_network
  start_sqlserver

  if [[ "${SKIP_RESTORE}" -eq 0 ]]; then
    restore_backup
  else
    log "Skipping restore (--skip-restore)"
    [[ -f "${WORK_DIR}/dbname.txt" ]] || die "--skip-restore requires ${WORK_DIR}/dbname.txt from a prior --keep-sqlserver run"
  fi

  if [[ "${SKIP_EXPORT}" -eq 0 ]]; then
    export_parquet
  else
    log "Skipping export (--skip-export)"
  fi

  teardown
  log "Done. Table files: ${OUT_DIR}/tables (${FORMAT})"
  log "Manifest: ${OUT_DIR}/export_manifest.csv"
  if [[ "${SKIP_DOCS}" -eq 0 && "${SKIP_EXPORT}" -eq 0 ]]; then
    log "Legacy guide: ${OUT_DIR}/legacy_database.md"
    log "ER diagram: ${OUT_DIR}/er_diagram.md"
  fi
}

main "$@"
