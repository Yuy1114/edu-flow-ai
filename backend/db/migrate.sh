#!/usr/bin/env bash
set -Eeuo pipefail

# The MySQL image only executes /docker-entrypoint-initdb.d for a brand-new
# data directory. This runner also applies migrations to existing volumes.
db_host="${DB_HOST:-db}"
db_port="${DB_PORT:-3306}"
db_name="${DB_NAME:-edu_flow_ai}"
db_user="${DB_USERNAME:-root}"
migration_root="${MIGRATION_ROOT:-/migrations}"

export MYSQL_PWD="${DB_PASSWORD:?DB_PASSWORD is required}"
mysql_cmd=(mysql --protocol=TCP --host="${db_host}" --port="${db_port}" --user="${db_user}" --default-character-set=utf8mb4)

until "${mysql_cmd[@]}" --execute="SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

# CREATE TABLE IF NOT EXISTS makes the canonical schema safe for both an empty
# database and an old volume. Versioned migrations add fields to old tables.
"${mysql_cmd[@]}" < "${migration_root}/schema.sql"
"${mysql_cmd[@]}" "${db_name}" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migration (
    version VARCHAR(128) PRIMARY KEY,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
SQL

apply_migration() {
  local version="$1"
  local file="$2"
  local applied
  applied="$("${mysql_cmd[@]}" --batch --skip-column-names "${db_name}" \
    --execute="SELECT COUNT(*) FROM schema_migration WHERE version = '${version}'")"
  if [[ "${applied}" == "1" ]]; then
    echo "migration ${version}: already applied"
    return
  fi

  echo "migration ${version}: applying"
  # Select DB_NAME at the client boundary.  New migrations must not hard-code
  # a USE statement; legacy migrations keep working with the default database.
  "${mysql_cmd[@]}" "${db_name}" < "${migration_root}/${file}"
  "${mysql_cmd[@]}" "${db_name}" \
    --execute="INSERT INTO schema_migration(version) VALUES ('${version}')"
}

apply_migration "002_teaching_task_batch" "002_teaching_task_batch.sql"
apply_migration "003_unify_atomic_time_slots" "003_unify_atomic_time_slots.sql"
apply_migration "v35_001_schedule_template_tables" "v3.5/001_schedule_template_tables.sql"
apply_migration "v35_002_template_generation_run_id" "v3.5/002_template_generation_run_id.sql"
apply_migration "004_schedule_generation_run" "004_schedule_generation_run.sql"
apply_migration "005_course_assignment_consecutive_slots" "005_course_assignment_consecutive_slots.sql"
apply_migration "006_teaching_task_explicit_pattern" "006_teaching_task_explicit_pattern.sql"
apply_migration "007_allocation_scheme_model_version" "007_allocation_scheme_model_version.sql"
apply_migration "008_allocation_task_status" "008_allocation_task_status.sql"
apply_migration "009_normalize_room_type_encoding" "009_normalize_room_type_encoding.sql"
apply_migration "010_schedule_publication_lock" "010_schedule_publication_lock.sql"
apply_migration "011_schedule_template_fragment_week" "011_schedule_template_fragment_week.sql"
apply_migration "012_validate_atomic_time_axis" "012_validate_atomic_time_axis.sql"
apply_migration "013_validate_course_assignment_span" "013_validate_course_assignment_span.sql"
apply_migration "014_extend_evening_to_period_11" "014_extend_evening_to_period_11.sql"
apply_migration "015_import_batch" "015_import_batch.sql"
apply_migration "016_dataset_quality_snapshot" "016_dataset_quality_snapshot.sql"

echo "database migrations complete"
