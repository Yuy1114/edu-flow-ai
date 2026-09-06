#!/usr/bin/env python3
"""
将 parsed/ 下的 5 个 JSONL 导入 MySQL。

导入顺序（按 FK 依赖）：
  1. teacher
  2. teacher_department
  3. course
  4. class_group
  5. classroom
  6. time_slot
  7. teaching_task
  8. teaching_task_class_group

用法：
  cd backend
  python3 python/scripts/import_to_db.py
  python3 python/scripts/import_to_db.py --dry-run   # 只打印不执行
"""

import argparse
import json
import sys
from pathlib import Path

import pymysql

# ─── 路径 ───────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "parsed"

# ─── DB 连接 ────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "20041114Liuyu!",
    "database": "edu_flow_ai",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


# ─── 加载 JSONL ─────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ─── 导入函数（单表） ────────────────────────────────

def import_teachers(cur, rows: list[dict]) -> dict[str, int]:
    """导入教师，返回 {name: id} 映射"""
    mapping = {}
    sql = """INSERT INTO teacher (employee_no, password, role, name, department, status)
             VALUES (%s, %s, 'TEACHER', %s, %s, 'ACTIVE')
             ON DUPLICATE KEY UPDATE name=VALUES(name), department=VALUES(department)"""
    for i, t in enumerate(rows):
        name = t["name"]
        dept = t.get("department", "电子信息与计算机工程系(学院)")
        emp_no = f"T{i + 1:06d}"
        cur.execute(sql, (emp_no, "123456", name, dept))
        cur.execute("SELECT id FROM teacher WHERE employee_no = %s", (emp_no,))
        row = cur.fetchone()
        mapping[name] = row["id"]
    return mapping


def import_teacher_departments(cur, teachers: dict[str, dict]) -> None:
    """导入教师多院系归属"""
    sql = """INSERT IGNORE INTO teacher_department (teacher_id, department, is_primary)
             VALUES (%s, %s, %s)"""
    count = 0
    for name, info in teachers.items():
        depts = info.get("departments", [])
        tid = info.get("_db_id")
        if not tid:
            continue
        for i, dept in enumerate(depts):
            cur.execute(sql, (tid, dept, 1 if i == 0 else 0))
            count += 1
    return count


def import_courses(cur, rows: list[dict]) -> dict[str, int]:
    """导入课程，返回 {code: id} 映射"""
    mapping = {}
    sql = """INSERT INTO course (name, code, course_type, required_room_type, required_hours, status)
             VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
             ON DUPLICATE KEY UPDATE name=VALUES(name), course_type=VALUES(course_type),
                                      required_room_type=VALUES(required_room_type)"""
    for c in rows:
        cur.execute(sql, (
            c.get("name", c["code"]),
            c["code"],
            c.get("course_type", "理论课"),
            c.get("required_room_type", None),
            None,  # required_hours
        ))
        cur.execute("SELECT id FROM course WHERE code = %s", (c["code"],))
        row = cur.fetchone()
        mapping[c["code"]] = row["id"]
    return mapping


def import_class_groups(cur, rows: list[dict]) -> dict[str, int]:
    """导入班级，返回 {name: id} 映射"""
    mapping = {}
    sql = """INSERT INTO class_group (name, major, department, grade, student_count)
             VALUES (%s, %s, %s, %s, %s)
             ON DUPLICATE KEY UPDATE major=VALUES(major), department=VALUES(department),
                                      grade=VALUES(grade), student_count=VALUES(student_count)"""
    for cg in rows:
        cur.execute(sql, (
            cg["name"],
            cg.get("major", ""),
            cg.get("department", ""),
            cg.get("grade", ""),
            cg.get("student_count", 0),
        ))
        cur.execute("SELECT id FROM class_group WHERE name = %s", (cg["name"],))
        row = cur.fetchone()
        mapping[cg["name"]] = row["id"]
    return mapping


def import_classrooms(cur, rows: list[dict]) -> dict[str, int]:
    """导入教室，返回 {name: id} 映射"""
    mapping = {}
    sql = """INSERT INTO classroom (name, classroom_type, status)
             VALUES (%s, %s, 'ACTIVE')
             ON DUPLICATE KEY UPDATE classroom_type=VALUES(classroom_type)"""
    for cr in rows:
        ctype = cr.get("classroom_type", "普通教室")
        cur.execute(sql, (cr["name"], ctype))
        cur.execute("SELECT id FROM classroom WHERE name = %s", (cr["name"],))
        row = cur.fetchone()
        mapping[cr["name"]] = row["id"]
    return mapping


def import_time_slots(cur) -> dict[tuple, int]:
    """生成 18 周 × 7 天 × 10 个原子节次，返回 {(week,day,period): id}。"""
    mapping = {}
    sql = """INSERT IGNORE INTO time_slot (week_number, day_of_week, period_index, label)
             VALUES (%s, %s, %s, %s)"""
    day_names = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    count = 0
    for w in range(1, 19):
        for d in range(1, 8):
            for p in range(1, 12):
                label = f"第{w}周 {day_names[d]} 第{p}节"
                cur.execute(sql, (w, d, p, label))
                cur.execute(
                    "SELECT id FROM time_slot WHERE week_number=%s AND day_of_week=%s AND period_index=%s",
                    (w, d, p),
                )
                row = cur.fetchone()
                mapping[(w, d, p)] = row["id"]
                count += 1
    return mapping


def import_teaching_tasks(
    cur,
    tasks: list[dict],
    teacher_map: dict[str, int],
    course_map: dict[str, int],
    class_group_map: dict[str, int],
) -> list[int]:
    """导入教学任务，返回 task_id 列表"""
    task_ids = []
    sql = """INSERT INTO teaching_task
             (course_id, primary_teacher_id, total_hours, required_room_type, status)
             VALUES (%s, %s, %s, %s, 'ACTIVE')"""
    for t in tasks:
        course_id = course_map.get(t["course_code"])
        teacher_id = teacher_map.get(t["teacher_name"])
        if not course_id or not teacher_id:
            continue
        cur.execute(sql, (
            course_id,
            teacher_id,
            t["total_hours"],
            t.get("required_room_type"),
        ))
        task_ids.append((cur.lastrowid, t["class_group_name"]))
    return task_ids


def import_task_class_groups(cur, task_ids: list[tuple], class_group_map: dict[str, int]) -> int:
    """导入教学任务-班级关联"""
    sql = """INSERT IGNORE INTO teaching_task_class_group (teaching_task_id, class_group_id)
             VALUES (%s, %s)"""
    count = 0
    for task_db_id, class_name in task_ids:
        cg_id = class_group_map.get(class_name)
        if cg_id:
            cur.execute(sql, (task_db_id, cg_id))
            count += 1
    return count


# ─── 主流程 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="导入课表 JSONL 到 MySQL")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不执行导入")
    args = parser.parse_args()

    # 加载数据
    teachers_raw = load_jsonl(DATA_DIR / "teachers.jsonl")
    class_groups_raw = load_jsonl(DATA_DIR / "class_groups.jsonl")
    courses_raw = load_jsonl(DATA_DIR / "courses.jsonl")
    classrooms_raw = load_jsonl(DATA_DIR / "classrooms.jsonl")
    tasks_raw = load_jsonl(DATA_DIR / "teaching_tasks.jsonl")

    print("=" * 50)
    print("数据总览")
    print("=" * 50)
    print(f"  教师:        {len(teachers_raw)}")
    print(f"  班级:        {len(class_groups_raw)}")
    print(f"  课程:        {len(courses_raw)}")
    print(f"  教室:        {len(classrooms_raw)}")
    print(f"  教学任务:    {len(tasks_raw)}")
    print(f"  time_slot:   630 (18周×7天×5节次)")
    print()

    if args.dry_run:
        print("[dry-run] 结束，未执行任何 SQL")
        return

    # 连接 DB
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            # 清空旧数据（按 FK 逆序）
            print("清空旧数据...")
            for tbl in [
                "teaching_task_class_group",
                "teaching_task",
                "time_slot",
                "classroom",
                "class_group",
                "course",
                "teacher_department",
                "teacher_profile",
                "teacher",
            ]:
                cur.execute(f"DELETE FROM {tbl}")
            conn.commit()

            # 1. 教师
            print("[1/8] 导入 teacher...")
            teacher_map = import_teachers(cur, teachers_raw)
            conn.commit()
            print(f"  → {len(teacher_map)} 位教师")

            # 2. 教师-院系（teachers_raw 没有 departments 数组，先跳过或手动补）
            # 这里我们从 teachers_raw 里取 department 字段写入 teacher_department
            print("[2/8] 导入 teacher_department...")
            td_count = 0
            for t in teachers_raw:
                tid = teacher_map.get(t["name"])
                if tid:
                    dept = t.get("department", "电子信息与计算机工程系(学院)")
                    cur.execute(
                        "INSERT IGNORE INTO teacher_department (teacher_id, department, is_primary) VALUES (%s, %s, 1)",
                        (tid, dept),
                    )
                    td_count += 1
            conn.commit()
            print(f"  → {td_count} 条归属记录")

            # 3. 课程
            print("[3/8] 导入 course...")
            course_map = import_courses(cur, courses_raw)
            conn.commit()
            print(f"  → {len(course_map)} 门课程")

            # 4. 班级
            print("[4/8] 导入 class_group...")
            cg_map = import_class_groups(cur, class_groups_raw)
            conn.commit()
            print(f"  → {len(cg_map)} 个班级")

            # 5. 教室
            print("[5/8] 导入 classroom...")
            classroom_map = import_classrooms(cur, classrooms_raw)
            conn.commit()
            print(f"  → {len(classroom_map)} 间教室")

            # 6. 时间段
            print("[6/8] 导入 time_slot...")
            ts_map = import_time_slots(cur)
            conn.commit()
            print(f"  → {len(ts_map)} 个时间段")

            # 7. 教学任务
            print("[7/8] 导入 teaching_task...")
            task_ids = import_teaching_tasks(cur, tasks_raw, teacher_map, course_map, cg_map)
            conn.commit()
            print(f"  → {len(task_ids)} 个教学任务")

            # 8. 教学任务-班级关联
            print("[8/8] 导入 teaching_task_class_group...")
            link_count = import_task_class_groups(cur, task_ids, cg_map)
            conn.commit()
            print(f"  → {link_count} 条关联")

        print()
        print("✅ 全部导入完成")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 导入失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
