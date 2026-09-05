#!/usr/bin/env bash
set -Eeuo pipefail

# MySQL integration contract for migration 013.  It uses an isolated temporary
# database and proves both the valid path and each fail-closed legacy-data path.
db_host="${DB_HOST:-127.0.0.1}"
db_port="${DB_PORT:-3306}"
db_user="${DB_USERNAME:-root}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
migration_file="${script_dir}/../013_validate_course_assignment_span.sql"
test_db="edu_flow_ai_test_013_${RANDOM}_$$"

if [[ ! "${test_db}" =~ ^edu_flow_ai_test_013_[0-9]+_[0-9]+$ ]]; then
  echo "unsafe temporary database name: ${test_db}" >&2
  exit 1
fi

export MYSQL_PWD="${DB_PASSWORD:?DB_PASSWORD is required}"
mysql_cmd=(mysql --protocol=TCP --host="${db_host}" --port="${db_port}" --user="${db_user}" --default-character-set=utf8mb4)

cleanup() {
  "${mysql_cmd[@]}" --execute="DROP DATABASE IF EXISTS \`${test_db}\`" >/dev/null 2>&1 || true
}
trap cleanup EXIT

reset_fixture() {
  "${mysql_cmd[@]}" --execute="DROP DATABASE IF EXISTS \`${test_db}\`; CREATE DATABASE \`${test_db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  "${mysql_cmd[@]}" "${test_db}" <<'SQL'
CREATE TABLE course (
    id BIGINT PRIMARY KEY,
    course_type VARCHAR(20) NULL
);
CREATE TABLE teaching_task (
    id BIGINT PRIMARY KEY,
    course_id BIGINT NOT NULL
);
CREATE TABLE time_slot (
    id BIGINT PRIMARY KEY,
    period_index INT NOT NULL
);
CREATE TABLE course_assignment (
    id BIGINT PRIMARY KEY,
    teaching_task_id BIGINT NOT NULL,
    time_slot_id BIGINT NOT NULL,
    consecutive_slots INT NOT NULL,
    CONSTRAINT chk_course_assignment_consecutive_slots CHECK (consecutive_slots BETWEEN 1 AND 10)
);
INSERT INTO course (id, course_type) VALUES
    (1, '理论课'),
    (2, '实践课'),
    (3, '上机课'),
    (4, '实验课');
INSERT INTO teaching_task (id, course_id) VALUES
    (1, 1), (2, 2), (3, 3), (4, 4);
INSERT INTO time_slot (id, period_index) VALUES
    (1, 1), (2, 2), (3, 3), (4, 5), (5, 9), (6, 10);
SQL
}

expect_migration_rejection() {
  local description="$1"
  if "${mysql_cmd[@]}" "${test_db}" < "${migration_file}" >/dev/null 2>&1; then
    echo "migration 013 unexpectedly accepted ${description}" >&2
    exit 1
  fi
}

reset_fixture
"${mysql_cmd[@]}" "${test_db}" --execute="
INSERT INTO course_assignment VALUES
    (1, 1, 1, 2),
    (2, 2, 6, 1),
    (3, 3, 4, 4),
    (4, 4, 4, 4);"
"${mysql_cmd[@]}" "${test_db}" < "${migration_file}"
if "${mysql_cmd[@]}" "${test_db}" --execute="INSERT INTO course_assignment VALUES (5, 1, 1, 3)" >/dev/null 2>&1; then
  echo "tightened CHECK unexpectedly accepted a three-period span" >&2
  exit 1
fi

reset_fixture
"${mysql_cmd[@]}" "${test_db}" --execute="INSERT INTO course_assignment VALUES (1, 1, 1, 4)"
expect_migration_rejection "a four-period theory assignment"

reset_fixture
"${mysql_cmd[@]}" "${test_db}" --execute="INSERT INTO course_assignment VALUES (1, 1, 2, 2)"
expect_migration_rejection "a two-period assignment starting at period 2"

reset_fixture
"${mysql_cmd[@]}" "${test_db}" --execute="INSERT INTO course_assignment VALUES (1, 3, 5, 4)"
expect_migration_rejection "a four-period assignment crossing the evening boundary"

echo "migration 013 course-assignment span contract: ok"
