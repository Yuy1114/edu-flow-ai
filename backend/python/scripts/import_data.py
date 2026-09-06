#!/usr/bin/env python3
"""Clean the real JSONL dataset and optionally import it into MySQL.

The pipeline is intentionally deterministic:
1. read raw JSONL files from data/real-dataset;
2. filter all records to one department;
3. write clean table-shaped JSONL files to data/imported;
4. optionally upsert/import the cleaned records in foreign-key order.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


DEFAULT_DEPARTMENT = "电子信息与计算机工程系(学院)"
DEFAULT_DB_PASSWORD = "20041114Liuyu!"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "real-dataset"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "imported"

@dataclass(frozen=True)
class TeacherRow:
    employee_no: str
    password: str
    role: str
    name: str
    department: str
    title: str | None = None
    status: str = "ACTIVE"


@dataclass(frozen=True)
class TeacherDepartmentRow:
    employee_no: str
    teacher_name: str
    department: str
    is_primary: bool


@dataclass(frozen=True)
class TeacherProfileRow:
    employee_no: str
    teacher_name: str
    availability_matrix_json: str
    profile_note: str
    profile_preference_json: str


@dataclass(frozen=True)
class CourseRow:
    name: str
    code: str
    credits: str | None
    course_type: str
    required_room_type: str | None
    required_hours: int | None
    description: str | None = None
    status: str = "ACTIVE"


@dataclass(frozen=True)
class ClassGroupRow:
    name: str
    major: str | None
    department: str | None
    grade: str | None
    student_count: int | None


@dataclass(frozen=True)
class ClassroomRow:
    name: str
    building: str | None
    capacity: int | None
    classroom_type: str
    status: str = "ACTIVE"


@dataclass(frozen=True)
class TimeSlotRow:
    week_number: int
    day_of_week: int
    period_index: int
    label: str


@dataclass(frozen=True)
class TeachingTaskRow:
    import_key: str
    course_code: str
    course_name: str
    teacher_name: str
    teacher_employee_no: str
    class_group_name: str
    classroom_name: str | None
    candidate_classrooms: list[str]
    total_hours: int
    required_room_type: str | None
    notes: str | None
    status: str = "ACTIVE"


@dataclass(frozen=True)
class TeachingTaskClassGroupRow:
    teaching_task_import_key: str
    class_group_name: str


@dataclass
class CleanDataset:
    teacher: list[TeacherRow] = field(default_factory=list)
    teacher_department: list[TeacherDepartmentRow] = field(default_factory=list)
    teacher_profile: list[TeacherProfileRow] = field(default_factory=list)
    course: list[CourseRow] = field(default_factory=list)
    class_group: list[ClassGroupRow] = field(default_factory=list)
    classroom: list[ClassroomRow] = field(default_factory=list)
    time_slot: list[TimeSlotRow] = field(default_factory=list)
    teaching_task: list[TeachingTaskRow] = field(default_factory=list)
    teaching_task_class_group: list[TeachingTaskClassGroupRow] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file and fail with line context on malformed JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Missing required input file: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object in {path} at line {line_no}")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = asdict(row) if hasattr(row, "__dataclass_fields__") else row
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def unique_clean(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(round(float(value)))


def to_decimal_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.1")))


def course_type_for(name: str) -> str:
    if "实训" in name or "课程设计" in name:
        return "实践课"
    return "理论课"


def is_excluded_room(name: str) -> bool:
    lower = name.lower()
    return lower.startswith("xn") or "操场" in name or "体育" in name


def classroom_type_for(name: str) -> str:
    return "机房" if name.startswith(("08", "09", "10")) else "普通教室"


def required_room_type_for(course_type: str, room_names: list[str]) -> str | None:
    if course_type == "实践课":
        return None
    if any(classroom_type_for(room) == "机房" for room in room_names if not is_excluded_room(room)):
        return "机房"
    return "普通教室"


def build_time_slots() -> list[TimeSlotRow]:
    return [
        TimeSlotRow(
            week_number=week,
            day_of_week=day,
            period_index=period,
            label=f"第{week}周 周{day} 第{period}节",
        )
        for week in range(1, 19)
        for day in range(1, 8)
        for period in range(1, 12)
    ]


def build_raw_indices(raw_dir: Path) -> dict[str, Any]:
    teachers = read_jsonl(raw_dir / "teachers.jsonl")
    courses = read_jsonl(raw_dir / "courses.jsonl")
    classrooms = read_jsonl(raw_dir / "classrooms.jsonl")
    class_groups = read_jsonl(raw_dir / "class_groups.jsonl")
    teaching_tasks = read_jsonl(raw_dir / "teaching_tasks.jsonl")

    teacher_by_name: dict[str, dict[str, Any]] = {}
    for row in teachers:
        name = clean_text(row.get("name"))
        if not name:
            continue
        current = teacher_by_name.setdefault(name, {"name": name, "departments": [], "courses": []})
        current["departments"] = list(dict.fromkeys(current["departments"] + unique_clean(row.get("departments"))))
        current["courses"] = list(dict.fromkeys(current["courses"] + unique_clean(row.get("courses"))))

    return {
        "teachers": teachers,
        "teacher_by_name": teacher_by_name,
        "course_by_code": {
            code: row
            for row in courses
            if (code := clean_text(row.get("code")))
        },
        "classroom_by_name": {
            name: row
            for row in classrooms
            if (name := clean_text(row.get("name")))
        },
        "class_group_by_name": {
            name: row
            for row in class_groups
            if (name := clean_text(row.get("key")))
        },
        "teaching_tasks": teaching_tasks,
    }


def clean_dataset(raw_dir: Path, department: str) -> CleanDataset:
    raw = build_raw_indices(raw_dir)
    dataset = CleanDataset(time_slot=build_time_slots())

    filtered_teachers = [
        teacher
        for teacher in raw["teacher_by_name"].values()
        if department in unique_clean(teacher.get("departments"))
    ]
    filtered_teachers.sort(key=lambda item: item["name"])

    teacher_names = {teacher["name"] for teacher in filtered_teachers}
    teacher_course_codes = {
        code
        for teacher in filtered_teachers
        for code in unique_clean(teacher.get("courses"))
    }

    employee_no_by_name: dict[str, str] = {}
    for index, teacher in enumerate(filtered_teachers, start=1):
        employee_no = f"T{index:06d}"
        employee_no_by_name[teacher["name"]] = employee_no
        departments = unique_clean(teacher.get("departments"))
        dataset.teacher.append(
            TeacherRow(
                employee_no=employee_no,
                password="123456",
                role="TEACHER",
                name=teacher["name"],
                department=department,
            )
        )
        for dept_index, dept in enumerate(departments):
            dataset.teacher_department.append(
                TeacherDepartmentRow(
                    employee_no=employee_no,
                    teacher_name=teacher["name"],
                    department=dept,
                    is_primary=(dept == department or dept_index == 0),
                )
            )
        dataset.teacher_profile.append(
            TeacherProfileRow(
                employee_no=employee_no,
                teacher_name=teacher["name"],
                availability_matrix_json=json.dumps([[0] * 7 for _ in range(10)], ensure_ascii=False),
                profile_note="",
                profile_preference_json=json.dumps({}, ensure_ascii=False),
            )
        )

    filtered_tasks: list[dict[str, Any]] = []
    for row in raw["teaching_tasks"]:
        teacher_name = clean_text(row.get("teacher"))
        if not teacher_name or teacher_name not in teacher_names:
            dataset.skipped["teaching_task_teacher_outside_department"] += 1
            continue
        course_code = clean_text(row.get("course_code"))
        class_group_name = clean_text(row.get("class_group"))
        if not course_code or not class_group_name:
            dataset.skipped["teaching_task_missing_course_or_class"] += 1
            continue
        filtered_tasks.append(row)

    task_course_codes = {clean_text(row.get("course_code")) for row in filtered_tasks}
    task_course_codes.discard(None)
    required_course_codes = set(teacher_course_codes) | set(task_course_codes)

    course_rows: dict[str, CourseRow] = {}
    for code in sorted(required_course_codes):
        raw_course = raw["course_by_code"].get(code)
        if raw_course:
            name = clean_text(raw_course.get("name")) or code
            rooms = unique_clean(raw_course.get("rooms"))
            credits = to_decimal_string(raw_course.get("credits"))
            hours = to_int(raw_course.get("hours"))
        else:
            matching_task = next(
                (task for task in filtered_tasks if clean_text(task.get("course_code")) == code),
                {},
            )
            name = clean_text(matching_task.get("course_name")) or code
            rooms = unique_clean(matching_task.get("rooms"))
            credits = None
            hours = to_int(matching_task.get("total_hours"))
            dataset.skipped["course_missing_from_catalog_created_from_task"] += 1
        course_type = course_type_for(name)
        course_rows[code] = CourseRow(
            name=name,
            code=code,
            credits=credits,
            course_type=course_type,
            required_room_type=required_room_type_for(course_type, rooms),
            required_hours=hours,
            description=None,
        )
    dataset.course = [course_rows[code] for code in sorted(course_rows)]

    referenced_class_groups = {clean_text(row.get("class_group")) for row in filtered_tasks}
    referenced_class_groups.discard(None)
    for name in sorted(referenced_class_groups):
        raw_group = raw["class_group_by_name"].get(name)
        source_task = next((task for task in filtered_tasks if clean_text(task.get("class_group")) == name), {})
        if not raw_group:
            dataset.skipped["class_group_missing_from_catalog_created_from_task"] += 1
        dataset.class_group.append(
            ClassGroupRow(
                name=name,
                major=clean_text((raw_group or source_task).get("major")),
                department=clean_text((raw_group or {}).get("department")) or department,
                grade=str((raw_group or source_task).get("grade")) if (raw_group or source_task).get("grade") is not None else None,
                student_count=to_int((raw_group or {}).get("student_count")),
            )
        )

    referenced_rooms: set[str] = set()
    for task in filtered_tasks:
        for room in unique_clean(task.get("rooms")):
            if is_excluded_room(room):
                dataset.skipped["classroom_excluded"] += 1
                continue
            referenced_rooms.add(room)

    for name in sorted(referenced_rooms):
        raw_room = raw["classroom_by_name"].get(name)
        if raw_room is None:
            dataset.skipped["classroom_missing_from_catalog_created_from_task"] += 1
        dataset.classroom.append(
            ClassroomRow(
                name=name,
                building=None,
                capacity=None,
                classroom_type=classroom_type_for(name),
            )
        )

    class_group_names = {row.name for row in dataset.class_group}
    course_codes = {row.code for row in dataset.course}
    task_key_occurrences: Counter[str] = Counter()
    for row in filtered_tasks:
        course_code = clean_text(row.get("course_code"))
        course_name = clean_text(row.get("course_name")) or course_code
        teacher_name = clean_text(row.get("teacher"))
        class_group_name = clean_text(row.get("class_group"))
        if not course_code or course_code not in course_codes or not teacher_name or not class_group_name:
            dataset.skipped["teaching_task_missing_clean_reference"] += 1
            continue
        if class_group_name not in class_group_names:
            dataset.skipped["teaching_task_missing_clean_class_group"] += 1
            continue
        valid_rooms = [room for room in unique_clean(row.get("rooms")) if not is_excluded_room(room)]
        primary_room = valid_rooms[0] if valid_rooms else None
        course = course_rows[course_code]
        total_hours = to_int(row.get("total_hours")) or course.required_hours or 0
        base_import_key = "|".join([course_code, teacher_name, class_group_name, str(total_hours)])
        task_key_occurrences[base_import_key] += 1
        import_key = f"{base_import_key}|{task_key_occurrences[base_import_key]}"
        dataset.teaching_task.append(
            TeachingTaskRow(
                import_key=import_key,
                course_code=course_code,
                course_name=course_name or course_code,
                teacher_name=teacher_name,
                teacher_employee_no=employee_no_by_name[teacher_name],
                class_group_name=class_group_name,
                classroom_name=primary_room,
                candidate_classrooms=valid_rooms,
                total_hours=total_hours,
                required_room_type=course.required_room_type,
                notes=json.dumps(
                    {
                        "import_key": import_key,
                        "semester": clean_text(row.get("semester")),
                        "candidate_classrooms": valid_rooms,
                        "class_group": class_group_name,
                        "source": "data/real-dataset/teaching_tasks.jsonl",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
        dataset.teaching_task_class_group.append(
            TeachingTaskClassGroupRow(
                teaching_task_import_key=import_key,
                class_group_name=class_group_name,
            )
        )

    return dataset


def export_dataset(dataset: CleanDataset, output_dir: Path) -> None:
    tables = [
        "teacher",
        "teacher_department",
        "teacher_profile",
        "course",
        "class_group",
        "classroom",
        "time_slot",
        "teaching_task",
        "teaching_task_class_group",
    ]
    for table in tables:
        write_jsonl(output_dir / f"{table}.jsonl", getattr(dataset, table))


class MySqlImporter:
    def __init__(self, args: argparse.Namespace) -> None:
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise SystemExit("Missing dependency: pymysql. Install backend/python dependencies first.") from exc

        self.pymysql = pymysql
        self.connection = pymysql.connect(
            host=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
            database=args.db_name,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    def close(self) -> None:
        self.connection.close()

    def executemany(self, sql: str, rows: list[dict[str, Any]]) -> None:
        if rows:
            with self.connection.cursor() as cursor:
                cursor.executemany(sql, rows)

    def fetch_map(self, sql: str, key_field: str, value_field: str = "id") -> dict[Any, int]:
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
            return {row[key_field]: row[value_field] for row in cursor.fetchall()}

    def import_dataset(self, dataset: CleanDataset) -> dict[str, int]:
        counts: dict[str, int] = {}
        try:
            self._import_teachers(dataset)
            teacher_id_by_employee_no = self.fetch_map("SELECT id, employee_no FROM teacher", "employee_no")
            self._import_teacher_departments(dataset, teacher_id_by_employee_no)
            self._import_teacher_profiles(dataset, teacher_id_by_employee_no)

            self._import_courses(dataset)
            course_id_by_code = self.fetch_map("SELECT id, code FROM course WHERE code IS NOT NULL", "code")

            self._import_class_groups(dataset)
            class_group_id_by_name = self.fetch_map("SELECT id, name FROM class_group", "name")

            self._import_classrooms(dataset)
            classroom_id_by_name = self.fetch_map("SELECT id, name FROM classroom", "name")

            self._import_time_slots(dataset)
            task_id_by_key = self._import_teaching_tasks(
                dataset,
                course_id_by_code,
                teacher_id_by_employee_no,
                classroom_id_by_name,
            )
            self._import_task_class_groups(dataset, task_id_by_key, class_group_id_by_name)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        for table in [
            "teacher",
            "teacher_department",
            "teacher_profile",
            "course",
            "class_group",
            "classroom",
            "time_slot",
            "teaching_task",
            "teaching_task_class_group",
        ]:
            counts[table] = len(getattr(dataset, table))
        return counts

    def _import_teachers(self, dataset: CleanDataset) -> None:
        self.executemany(
            """
            INSERT INTO teacher (employee_no, password, role, name, department, title, status)
            VALUES (%(employee_no)s, %(password)s, %(role)s, %(name)s, %(department)s, %(title)s, %(status)s)
            ON DUPLICATE KEY UPDATE
                password = VALUES(password),
                role = VALUES(role),
                name = VALUES(name),
                department = VALUES(department),
                title = VALUES(title),
                status = VALUES(status)
            """,
            [asdict(row) for row in dataset.teacher],
        )

    def _import_teacher_departments(
        self,
        dataset: CleanDataset,
        teacher_id_by_employee_no: dict[str, int],
    ) -> None:
        rows = [
            {
                "teacher_id": teacher_id_by_employee_no[row.employee_no],
                "department": row.department,
                "is_primary": row.is_primary,
            }
            for row in dataset.teacher_department
            if row.employee_no in teacher_id_by_employee_no
        ]
        self.executemany(
            """
            INSERT INTO teacher_department (teacher_id, department, is_primary)
            VALUES (%(teacher_id)s, %(department)s, %(is_primary)s)
            ON DUPLICATE KEY UPDATE is_primary = VALUES(is_primary)
            """,
            rows,
        )

    def _import_teacher_profiles(
        self,
        dataset: CleanDataset,
        teacher_id_by_employee_no: dict[str, int],
    ) -> None:
        rows = [
            {
                "teacher_id": teacher_id_by_employee_no[row.employee_no],
                "availability_matrix_json": row.availability_matrix_json,
                "profile_note": row.profile_note,
                "profile_preference_json": row.profile_preference_json,
            }
            for row in dataset.teacher_profile
            if row.employee_no in teacher_id_by_employee_no
        ]
        self.executemany(
            """
            INSERT INTO teacher_profile (
                teacher_id, availability_matrix_json, profile_note, profile_preference_json
            )
            VALUES (
                %(teacher_id)s, %(availability_matrix_json)s, %(profile_note)s, %(profile_preference_json)s
            )
            ON DUPLICATE KEY UPDATE
                availability_matrix_json = VALUES(availability_matrix_json),
                profile_note = VALUES(profile_note),
                profile_preference_json = VALUES(profile_preference_json)
            """,
            rows,
        )

    def _import_courses(self, dataset: CleanDataset) -> None:
        self.executemany(
            """
            INSERT INTO course (
                name, code, credits, course_type, required_room_type, required_hours, description, status
            )
            VALUES (
                %(name)s, %(code)s, %(credits)s, %(course_type)s, %(required_room_type)s,
                %(required_hours)s, %(description)s, %(status)s
            )
            ON DUPLICATE KEY UPDATE
                credits = VALUES(credits),
                course_type = VALUES(course_type),
                required_room_type = VALUES(required_room_type),
                required_hours = VALUES(required_hours),
                description = VALUES(description),
                status = VALUES(status)
            """,
            [asdict(row) for row in dataset.course],
        )

    def _import_class_groups(self, dataset: CleanDataset) -> None:
        self.executemany(
            """
            INSERT INTO class_group (name, major, department, grade, student_count)
            VALUES (%(name)s, %(major)s, %(department)s, %(grade)s, %(student_count)s)
            ON DUPLICATE KEY UPDATE
                major = VALUES(major),
                department = VALUES(department),
                grade = VALUES(grade),
                student_count = VALUES(student_count)
            """,
            [asdict(row) for row in dataset.class_group],
        )

    def _import_classrooms(self, dataset: CleanDataset) -> None:
        self.executemany(
            """
            INSERT INTO classroom (name, building, capacity, classroom_type, status)
            VALUES (%(name)s, %(building)s, %(capacity)s, %(classroom_type)s, %(status)s)
            ON DUPLICATE KEY UPDATE
                building = VALUES(building),
                capacity = VALUES(capacity),
                classroom_type = VALUES(classroom_type),
                status = VALUES(status)
            """,
            [asdict(row) for row in dataset.classroom],
        )

    def _import_time_slots(self, dataset: CleanDataset) -> None:
        self.executemany(
            """
            INSERT INTO time_slot (week_number, day_of_week, period_index, label)
            VALUES (%(week_number)s, %(day_of_week)s, %(period_index)s, %(label)s)
            ON DUPLICATE KEY UPDATE label = VALUES(label)
            """,
            [asdict(row) for row in dataset.time_slot],
        )

    def _import_teaching_tasks(
        self,
        dataset: CleanDataset,
        course_id_by_code: dict[str, int],
        teacher_id_by_employee_no: dict[str, int],
        classroom_id_by_name: dict[str, int],
    ) -> dict[str, int]:
        task_id_by_key = self._fetch_existing_task_keys()
        inserts: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []
        for row in dataset.teaching_task:
            payload = {
                "course_id": course_id_by_code[row.course_code],
                "primary_teacher_id": teacher_id_by_employee_no[row.teacher_employee_no],
                "classroom_id": classroom_id_by_name.get(row.classroom_name) if row.classroom_name else None,
                "total_hours": row.total_hours,
                "required_room_type": row.required_room_type,
                "notes": row.notes,
                "status": row.status,
                "import_key": row.import_key,
                "id": task_id_by_key.get(row.import_key),
            }
            if payload["id"]:
                updates.append(payload)
            else:
                inserts.append(payload)

        self.executemany(
            """
            UPDATE teaching_task
            SET course_id = %(course_id)s,
                primary_teacher_id = %(primary_teacher_id)s,
                classroom_id = %(classroom_id)s,
                total_hours = %(total_hours)s,
                required_room_type = %(required_room_type)s,
                notes = %(notes)s,
                status = %(status)s
            WHERE id = %(id)s
            """,
            updates,
        )
        self.executemany(
            """
            INSERT INTO teaching_task (
                course_id, primary_teacher_id, classroom_id, total_hours, required_room_type, notes, status
            )
            VALUES (
                %(course_id)s, %(primary_teacher_id)s, %(classroom_id)s, %(total_hours)s,
                %(required_room_type)s, %(notes)s, %(status)s
            )
            """,
            inserts,
        )
        if inserts:
            task_id_by_key = self._fetch_existing_task_keys()
        return task_id_by_key

    def _fetch_existing_task_keys(self) -> dict[str, int]:
        task_id_by_key: dict[str, int] = {}
        notes_sql = """
        SELECT id, notes
        FROM teaching_task
        WHERE notes LIKE '%"source": "data/real-dataset/teaching_tasks.jsonl"%'
        """
        with self.connection.cursor() as cursor:
            cursor.execute(notes_sql)
            for row in cursor.fetchall():
                try:
                    notes = json.loads(row["notes"] or "{}")
                except json.JSONDecodeError:
                    continue
                import_key = notes.get("import_key")
                if import_key:
                    task_id_by_key[str(import_key)] = row["id"]

        join_sql = """
        SELECT
            tt.id,
            c.code,
            t.name AS teacher_name,
            cg.name AS class_group_name,
            tt.total_hours
        FROM teaching_task tt
        JOIN course c ON c.id = tt.course_id
        JOIN teacher t ON t.id = tt.primary_teacher_id
        JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
        JOIN class_group cg ON cg.id = ttcg.class_group_id
        """
        with self.connection.cursor() as cursor:
            cursor.execute(join_sql)
            for row in cursor.fetchall():
                fallback_key = "|".join(
                    [
                        str(row["code"]),
                        str(row["teacher_name"]),
                        str(row["class_group_name"]),
                        str(row["total_hours"]),
                        "1",
                    ]
                )
                task_id_by_key.setdefault(
                    fallback_key,
                    row["id"],
                )
        return task_id_by_key

    def _import_task_class_groups(
        self,
        dataset: CleanDataset,
        task_id_by_key: dict[str, int],
        class_group_id_by_name: dict[str, int],
    ) -> None:
        rows = [
            {
                "teaching_task_id": task_id_by_key[row.teaching_task_import_key],
                "class_group_id": class_group_id_by_name[row.class_group_name],
            }
            for row in dataset.teaching_task_class_group
            if row.teaching_task_import_key in task_id_by_key and row.class_group_name in class_group_id_by_name
        ]
        self.executemany(
            """
            INSERT INTO teaching_task_class_group (teaching_task_id, class_group_id)
            VALUES (%(teaching_task_id)s, %(class_group_id)s)
            ON DUPLICATE KEY UPDATE class_group_id = VALUES(class_group_id)
            """,
            rows,
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import real dataset JSONL files into edu_flow_ai.")
    parser.add_argument("--department", default=DEFAULT_DEPARTMENT, help="Department to keep.")
    parser.add_argument("--dry-run", action="store_true", help="Only write clean JSONL files; skip MySQL import.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Clean JSONL output directory.")
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--db-port", type=int, default=3306)
    parser.add_argument("--db-user", default="root")
    parser.add_argument("--db-password", default=DEFAULT_DB_PASSWORD)
    parser.add_argument("--db-name", default="edu_flow_ai")
    return parser.parse_args(argv)


def print_summary(dataset: CleanDataset, output_dir: Path, imported: bool) -> None:
    print("Import data pipeline summary")
    print(f"  output_dir: {output_dir}")
    print(f"  mysql_imported: {imported}")
    for table in [
        "teacher",
        "teacher_department",
        "teacher_profile",
        "course",
        "class_group",
        "classroom",
        "time_slot",
        "teaching_task",
        "teaching_task_class_group",
    ]:
        print(f"  {table}: {len(getattr(dataset, table))}")
    if dataset.skipped:
        print("  skipped/warnings:")
        for key, count in sorted(dataset.skipped.items()):
            print(f"    {key}: {count}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    dataset = clean_dataset(RAW_DATA_DIR, args.department)
    export_dataset(dataset, args.output_dir)

    imported = False
    if not args.dry_run:
        importer = MySqlImporter(args)
        try:
            importer.import_dataset(dataset)
            imported = True
        finally:
            importer.close()

    print_summary(dataset, args.output_dir, imported)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
