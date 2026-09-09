"""Parse one class schedule .xlsx into CSV files.

This parser targets class timetable Excel files, not generic course-list files.
It is read-only and writes normalized CSV artifacts for later review/LLM steps.

Outputs:
- courses.csv
- teachers.csv
- classrooms.csv
- class_groups.csv
- teaching_tasks.csv
- timetable_occurrences.csv
- parse_intermediate.json
- parse_quality_report.json
- parse_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "parsed" / "schedule_imports"
PUBLIC_PHYSICAL_EDUCATION = "公共体育"
UNSCHEDULABLE_COURSES = {PUBLIC_PHYSICAL_EDUCATION}

# Keywords that make a course unschedulable (not needing normal classroom/time placement)
UNSCHEDULABLE_KEYWORDS = {
    "虚拟", "实训", "实习", "毕业", "毕业设计", "毕业论文", "军训", "创新创业",
    "就业指导", "形势与政策", "心理健康", "职业生涯",
    "第二课堂", "社会实践", "劳动教育", "通识选修",
}
PE_KEYWORDS = {"体育", "田径", "球类", "体操", "武术", "健美", "瑜伽", "跆拳道", "游泳", "太极"}
UNSCHEDULABLE_CODE_PREFIXES = ("毕", "虚")
BLOCKED_IMPORT_TOKENS = {"设392", "设387"}
RESOURCE_POINT_KEYWORDS = {
    "球场", "场地", "操场", "田径场", "足球场", "篮球场", "排球场", "网球场", "乒乓球场",
    "轮滑场", "攀岩墙", "体育馆", "训练馆", "游泳馆", "健身房", "舞蹈房", "形体中心", "中心",
    "实训室", "实训基地", "实践基地",
}
WEEKDAY_LABELS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
}
DETAIL_PATTERN = re.compile(
    r"(?P<name>[^\r\n\[\]]{2,80}?)"
    r"\((?P<code>[^()\[\]]+)\)"
    r"(?:\(ID\[(?P<course_id>[^\]]*)\]学分\[(?P<credits>[^\]]*)\]\)|.*?学分\[(?P<credits_alt>[^\]]*)\])?"
    r"\s*时\[(?P<hours>[^\]]*)\]"
    r"\s*师\[(?P<teachers>[^\]]*)\]"
    r"\s*室\[(?P<rooms>[^\]]*)\]",
    re.S,
)
COURSE_CODE_PATTERN = re.compile(r"^(?:[\u4e00-\u9fa5]{1,4}|[A-Za-z]{1,6})\d{2,4}$")
# 课表格子里的子区间标注，例如 高166(9-10)：晚间大节只用前两节。
PERIOD_ANNOTATION_PATTERN = re.compile(r"[\(（]\s*(\d{1,2})\s*[-~－]\s*(\d{1,2})\s*[\)）]")
# 教学周网格里合法出现的非教学内容：考试周、法定假日、集中活动。
# 它们不是解析失败，不该占用质量分；但仍然计数，便于核对。
NON_TEACHING_MARKERS = (
    "考试", "四、六级", "报到", "注册",
    "运动会", "校运会", "军训", "实习", "放假",
    "国庆", "中秋", "元旦", "清明", "端午", "五一", "春节", "劳动节",
)
CLASSROOM_PATTERN = re.compile(r"^\d{4,6}$")
RESOURCE_POINT_PATTERN = re.compile(r"^(?:xn|XN)\d{2,5}$")
LETTER_RESOURCE_POINT_PATTERN = re.compile(r"^[jJ]\d{3,5}$")
VIRTUAL_RESOURCE_POINT_PATTERN = re.compile(r"^虚拟(?:教室)?\d{1,5}$")
CLASS_LAB_RESOURCE_POINT_PATTERN = re.compile(r"^(?:cl|CL)\d{3,5}$")
META_PATTERN = re.compile(
    r"(?P<academic_year>\d{4}-\d{4})学年第(?P<semester>\d+)学期"
    r"(?P<department>.+?)\(学院\)"
    r"(?P<major>.+?)\(专业\)"
    r"(?P<class_name>.+?)\(班级\)课表共(?P<student_count>\d+)人"
)
CELL_REF_PATTERN = re.compile(r"([A-Z]+)(\d+)")


@dataclass(frozen=True)
class Cell:
    row: int
    col: int
    value: str


@dataclass(frozen=True)
class CourseDetail:
    course_id: str
    course_code: str
    course_name: str
    credits: str
    required_hours: str
    teachers: list[str]
    rooms: list[str]
    raw_text: str
    source_sheet: str = ""
    row_index: int = 0
    col_index: int = 0


@dataclass(frozen=True)
class Occurrence:
    class_name: str
    course_code: str
    classroom_name: str
    day_of_week: int
    period_index: int
    # 课表的列是"大节"，不是原子小节：12/34/56/78 各占 2 节，91011 占 3 节。
    # period_index 是大节的起始小节，consecutive_slots 是它实际占用的小节数。
    # 少了这一列，下游会把一次 2 节的课当成 1 节，课时直接减半。
    consecutive_slots: int
    week_index: int
    row_index: int
    col_index: int
    sheet_name: str
    raw_cell: str


def parse_schedule_excel(
    *,
    input_path: Path,
    output_dir: Path | None = None,
    class_name: str | None = None,
    major: str | None = None,
    department: str | None = None,
    grade: str | None = None,
    student_count: int | None = None,
    task_batch: str = "DEFAULT",
) -> dict[str, Any]:
    if input_path.suffix.lower() not in {".xlsx", ".xls"}:
        raise SystemExit("当前解析器支持 .xlsx / .xls 文件")

    output_dir = output_dir or DEFAULT_OUTPUT_ROOT / input_path.stem
    workbook = _read_workbook(input_path)
    if not workbook:
        raise SystemExit("Excel 中没有可解析的 sheet")

    first_sheet_name = next(iter(workbook.keys()))
    first_sheet = workbook[first_sheet_name]
    meta = _parse_meta(first_sheet, fallback={
        "class_name": class_name,
        "major": major,
        "department": department,
        "grade": grade,
        "student_count": student_count,
    })
    class_name_value = str(meta.get("class_name") or class_name or input_path.stem).strip()

    details_by_code: dict[str, CourseDetail] = {}
    all_details: list[CourseDetail] = []
    occurrences: list[Occurrence] = []
    warnings: list[dict[str, Any]] = []
    sheet_traces: list[dict[str, Any]] = []

    for sheet_name, cells in workbook.items():
        sheet_details = _extract_course_details(cells, sheet_name=sheet_name)
        all_details.extend(sheet_details)
        detected_day_cols = _detect_day_columns(cells)
        day_cols = dict(detected_day_cols)
        day_period_cols = _detect_day_period_columns(cells, day_cols)
        detected_period_rows = _detect_period_rows(cells)
        period_rows = dict(detected_period_rows)
        used_day_fallback = False
        used_period_fallback = False
        if not day_cols:
            warnings.append({"sheet": sheet_name, "warning": "未识别到星期列，使用 B-F 作为周一至周五兜底"})
            day_cols = {col: col - 1 for col in range(2, 7)}
            used_day_fallback = True
        if not day_period_cols and not period_rows:
            warnings.append({"sheet": sheet_name, "warning": "未识别到节次行，尝试按行号顺序兜底"})
            period_rows = _fallback_period_rows(cells)
            used_period_fallback = True
        sheet_occurrences, sheet_unparsed, sheet_non_teaching = _extract_occurrences(cells, sheet_name, class_name_value, day_cols, period_rows, day_period_cols)
        occurrences.extend(sheet_occurrences)
        sheet_traces.append(_sheet_trace(
            sheet_name=sheet_name,
            cells=cells,
            details=sheet_details,
            occurrences=sheet_occurrences,
            unparsed_cells=sheet_unparsed,
            non_teaching_cells=sheet_non_teaching,
            detected_day_cols=detected_day_cols,
            day_cols=day_cols,
            detected_period_rows=detected_period_rows,
            period_rows=period_rows,
            day_period_cols=day_period_cols,
            used_day_fallback=used_day_fallback,
            used_period_fallback=used_period_fallback,
        ))

    dropped_detail_codes = {
        detail.course_code
        for detail in all_details
        if _should_drop_course_detail(detail, class_name_value)
    }
    all_details = [
        detail
        for detail in all_details
        if detail.course_code not in dropped_detail_codes
    ]
    for detail in all_details:
        details_by_code.setdefault(detail.course_code, detail)
    occurrences = [
        item
        for item in occurrences
        if item.course_code in details_by_code
        and not _should_drop_occurrence(item, details_by_code.get(item.course_code), dropped_detail_codes)
    ]

    code_order = _ordered_codes(occurrences, details_by_code)
    courses = _build_courses(code_order, details_by_code, occurrences)
    teachers = _build_teachers(details_by_code)
    classrooms = _build_classrooms(details_by_code, occurrences, courses)
    class_groups = [_build_class_group(meta, class_name_value)]
    teaching_tasks = _build_teaching_tasks(class_name_value, task_batch, courses, details_by_code, occurrences)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "courses.csv", courses, [
        "course_id", "course_code", "course_name", "credits", "required_hours", "course_type", "required_room_type",
        "schedulable", "exclude_reason", "raw_text",
    ])
    _write_csv(output_dir / "teachers.csv", teachers, ["teacher_name", "department", "title", "raw_source"])
    _write_csv(output_dir / "classrooms.csv", classrooms, ["classroom_name", "classroom_type", "capacity", "status", "raw_source"])
    _write_csv(output_dir / "class_groups.csv", class_groups, [
        "class_name", "major", "department", "grade", "student_count", "academic_year", "semester",
    ])
    _write_csv(output_dir / "teaching_tasks.csv", teaching_tasks, [
        "course_id", "course_code", "course_name", "teacher_name", "class_name", "class_names", "total_hours", "required_room_type",
        "sessions_per_week", "duration_weeks", "session_slots", "observed_hours",
        "pattern_source", "pattern_regular", "active_weeks",
        "trainable", "untrainable_reason",
        "task_batch", "schedulable", "exclude_reason", "source",
    ])
    _write_csv(output_dir / "timetable_occurrences.csv", [_occurrence_row(item, details_by_code) for item in occurrences], [
        "class_name", "course_id", "course_code", "course_name", "teacher_name", "classroom_name", "day_of_week",
        "period_index", "consecutive_slots", "week_index", "row_index", "col_index", "sheet_name", "raw_cell",
    ])

    unmatched_occurrence_codes = sorted({
        item.course_code
        for item in occurrences
        if item.course_code not in details_by_code and item.course_code not in UNSCHEDULABLE_COURSES
    })
    intermediate = _build_intermediate(
        input_path=input_path,
        output_dir=output_dir,
        workbook=workbook,
        class_meta=class_groups[0],
        sheet_traces=sheet_traces,
        course_details=all_details,
        occurrences=occurrences,
        courses=courses,
        teachers=teachers,
        classrooms=classrooms,
        teaching_tasks=teaching_tasks,
    )
    quality_report = _build_quality_report(
        input_path=input_path,
        output_dir=output_dir,
        class_meta=class_groups[0],
        sheet_traces=sheet_traces,
        course_details=all_details,
        details_by_code=details_by_code,
        occurrences=occurrences,
        courses=courses,
        teaching_tasks=teaching_tasks,
        warnings=warnings,
        unmatched_occurrence_codes=unmatched_occurrence_codes,
    )
    (output_dir / "parse_intermediate.json").write_text(json.dumps(intermediate, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "parse_quality_report.json").write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "status": "ok",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "sheet_count": len(workbook),
        "sheets": list(workbook.keys()),
        "class_meta": class_groups[0],
        "counts": {
            "courses": len(courses),
            "teachers": len(teachers),
            "classrooms": len(classrooms),
            "class_groups": len(class_groups),
            "teaching_tasks": len(teaching_tasks),
            "timetable_occurrences": len(occurrences),
        },
        "warnings": warnings,
        "unmatched_occurrence_codes": unmatched_occurrence_codes,
        "intermediate_path": str(output_dir / "parse_intermediate.json"),
        "quality_report_path": str(output_dir / "parse_quality_report.json"),
        "quality": {
            "status": quality_report["status"],
            "score": quality_report["score"],
            "accepted": quality_report["gate"]["accepted"],
            "review_needed": quality_report["gate"]["review_needed"],
            "rejected": quality_report["gate"]["rejected"],
            "issue_counts": quality_report["issue_counts"],
        },
    }
    (output_dir / "parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _read_workbook(path: Path) -> dict[str, list[Cell]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _read_xlsx(path)
    if suffix == ".xls":
        return _read_xls(path)
    raise SystemExit(f"不支持的 Excel 文件格式: {path.suffix}")


def _read_xls(path: Path) -> dict[str, list[Cell]]:
    try:
        import xlrd
    except ModuleNotFoundError as exc:
        raise SystemExit("解析 .xls 需要 xlrd，请先安装 Python 依赖") from exc
    book = xlrd.open_workbook(str(path))
    result: dict[str, list[Cell]] = {}
    for sheet in book.sheets():
        cells: list[Cell] = []
        for row_index in range(sheet.nrows):
            for col_index in range(sheet.ncols):
                value = sheet.cell_value(row_index, col_index)
                text = _format_xls_value(value)
                if text.strip():
                    cells.append(Cell(row=row_index + 1, col=col_index + 1, value=text.strip()))
        result[sheet.name] = cells
    return result


def _format_xls_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value or "").strip()


def _read_xlsx(path: Path) -> dict[str, list[Cell]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_names = _read_sheet_names(archive)
        result: dict[str, list[Cell]] = {}
        for index, sheet_name in enumerate(sheet_names, start=1):
            sheet_path = f"xl/worksheets/sheet{index}.xml"
            if sheet_path not in archive.namelist():
                continue
            result[sheet_name] = _read_sheet_cells(archive, sheet_path, shared_strings)
        return result


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall(".//{*}si"):
        parts = [node.text or "" for node in si.findall(".//{*}t")]
        strings.append("".join(parts))
    return strings


def _read_sheet_names(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/workbook.xml"))
    names = [sheet.attrib.get("name") or f"Sheet{idx}" for idx, sheet in enumerate(root.findall(".//{*}sheet"), start=1)]
    return names or ["Sheet1"]


def _read_sheet_cells(archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[Cell]:
    root = ET.fromstring(archive.read(sheet_path))
    cells: list[Cell] = []
    for cell in root.findall(".//{*}c"):
        ref = cell.attrib.get("r", "")
        match = CELL_REF_PATTERN.match(ref)
        if not match:
            continue
        col = _col_to_index(match.group(1))
        row = int(match.group(2))
        value = _cell_value(cell, shared_strings)
        if value.strip():
            cells.append(Cell(row=row, col=col, value=value.strip()))
    return cells


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t"))
    value_node = cell.find("{*}v")
    if value_node is None or value_node.text is None:
        return ""
    raw_value = value_node.text
    if cell_type == "s":
        index = _safe_int(raw_value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    return raw_value


def _parse_meta(cells: list[Cell], fallback: dict[str, Any]) -> dict[str, Any]:
    text_candidates = [cell.value for cell in sorted(cells, key=lambda item: (item.row, item.col))[:20]]
    joined = " ".join(text_candidates)
    match = META_PATTERN.search(joined)
    meta = {
        "academic_year": "",
        "semester": "",
        "department": fallback.get("department") or "",
        "major": fallback.get("major") or "",
        "class_name": fallback.get("class_name") or "",
        "grade": fallback.get("grade") or "",
        "student_count": _student_count_value(fallback.get("student_count")),
    }
    if match:
        meta.update(match.groupdict())
        meta["grade"] = _infer_grade(meta["class_name"])
        meta["student_count"] = _student_count_value(meta["student_count"])
    if not meta.get("grade") and meta.get("class_name"):
        meta["grade"] = _infer_grade(str(meta["class_name"]))
    return meta


def _extract_course_details(cells: list[Cell], *, sheet_name: str = "") -> list[CourseDetail]:
    details: list[CourseDetail] = []
    for cell in cells:
        if "学分[" not in cell.value or "师[" not in cell.value or "时[" not in cell.value:
            continue
        for match in DETAIL_PATTERN.finditer(cell.value):
            raw_text = match.group(0).strip()
            code = _clean_token(match.group("code"))
            details.append(CourseDetail(
                course_id=_clean_token(match.group("course_id") or ""),
                course_code=code,
                course_name=_clean_course_name(match.group("name")),
                credits=_clean_token(match.group("credits") or match.group("credits_alt") or ""),
                required_hours=_clean_token(match.group("hours")),
                teachers=_split_list(match.group("teachers")),
                rooms=_split_list(match.group("rooms")),
                raw_text=raw_text,
                source_sheet=sheet_name,
                row_index=cell.row,
                col_index=cell.col,
            ))
    return details


def _detect_day_columns(cells: list[Cell]) -> dict[int, int]:
    result: dict[int, int] = {}
    for cell in cells:
        value = cell.value.replace("星期", "周")
        for label, day in WEEKDAY_LABELS.items():
            if f"周{label}" in value or f"星期{label}" in cell.value:
                result[cell.col] = day
    return result


def _detect_period_rows(cells: list[Cell]) -> dict[int, int]:
    result: dict[int, int] = {}
    for cell in cells:
        if cell.col > 3:
            continue
        value = cell.value.strip()
        match = re.search(r"第?([1-9]\d*)节", value)
        if not match:
            match = re.fullmatch(r"([1-9]\d*)", value)
        if match:
            period = _safe_int(match.group(1))
            if 1 <= period <= 12:
                result[cell.row] = period
    return result


def _detect_day_period_columns(cells: list[Cell], day_cols: dict[int, int]) -> dict[int, tuple[int, int, int]]:
    """列 -> (星期, 大节起始小节, 大节占用小节数)。"""
    if not day_cols:
        return {}
    header_by_col: dict[int, list[str]] = defaultdict(list)
    for cell in cells:
        if cell.row <= 5:
            header_by_col[cell.col].append(cell.value.strip())
    result: dict[int, tuple[int, int, int]] = {}
    sorted_day_cols = sorted(day_cols.items())
    for index, (start_col, day) in enumerate(sorted_day_cols):
        end_col = sorted_day_cols[index + 1][0] if index + 1 < len(sorted_day_cols) else start_col + 5
        for col in range(start_col, end_col):
            headers = header_by_col.get(col, [])
            period = _period_from_column_headers(headers)
            if period:
                result[col] = (day, period, _span_from_column_headers(headers))
    return result


def _period_from_column_headers(values: list[str]) -> int | None:
    for value in values:
        period = _period_from_column_header(value)
        if period:
            return period
    return None


def _span_from_column_headers(values: list[str]) -> int:
    for value in values:
        if _period_from_column_header(value):
            return _span_from_column_header(value)
    return 1


def _span_from_column_header(value: str) -> int:
    """大节占用的原子小节数。晚间 9-11 是 19:10-21:35 的三节大块，其余都是两节。"""
    normalized = _clean_token(value)
    if normalized in {"91011", "9-10-11", "9、10、11"}:
        return 3
    if normalized in {"12", "1-2", "1、2", "34", "3-4", "3、4",
                      "56", "5-6", "5、6", "78", "7-8", "7、8"}:
        return 2
    return 1


def _period_from_column_header(value: str) -> int | None:
    normalized = _clean_token(value)
    if normalized in {"12", "1-2", "1、2"}:
        return 1
    if normalized in {"34", "3-4", "3、4"}:
        return 3
    if normalized in {"56", "5-6", "5、6"}:
        return 5
    if normalized in {"78", "7-8", "7、8"}:
        return 7
    if normalized in {"91011", "9-10-11", "9、10、11"}:
        return 9
    match = re.fullmatch(r"([1-9]\d*)", normalized)
    if match:
        period = _safe_int(match.group(1))
        if 1 <= period <= 12:
            return period
    return None


def _fallback_period_rows(cells: list[Cell]) -> dict[int, int]:
    rows = sorted({cell.row for cell in cells if cell.row > 1})
    return {row: index for index, row in enumerate(rows[:12], start=1)}


def _extract_occurrences(
    cells: list[Cell],
    sheet_name: str,
    class_name: str,
    day_cols: dict[int, int],
    period_rows: dict[int, int],
    day_period_cols: dict[int, tuple[int, int, int]] | None = None,
) -> tuple[list[Occurrence], list[dict[str, Any]], list[dict[str, Any]]]:
    result: list[Occurrence] = []
    unparsed: list[dict[str, Any]] = []
    non_teaching: list[dict[str, Any]] = []
    for cell in cells:
        day = None
        period = None
        span = 1
        if day_period_cols and cell.col in day_period_cols:
            day, period, span = day_period_cols[cell.col]
        else:
            day = day_cols.get(cell.col)
            period = period_rows.get(cell.row)
        if not day or not period:
            continue
        parsed = _parse_timetable_cell(cell.value)
        if not parsed:
            # 只看教学周行；表头行（星期一 / 91011）本来就不含课程。考试周和假日
            # 是合法的非教学内容，单独计数；剩下的才是真正没解释的丢弃，必须报警。
            if _week_from_row(cell.row, cell.value) > 0:
                bucket = non_teaching if _is_non_teaching_marker(cell.value) else unparsed
                bucket.append({"row": cell.row, "col": cell.col, "value": cell.value})
            continue
        for course_code, classroom_name, override in parsed:
            occurrence_period = period
            occurrence_span = span
            if override:
                start, length = override
                # 子区间必须落在本列大节内部，否则以列头为准。
                if period <= start and start + length <= period + span:
                    occurrence_period = start
                    occurrence_span = length
            result.append(Occurrence(
                class_name=class_name,
                course_code=course_code,
                classroom_name=classroom_name,
                day_of_week=day,
                period_index=occurrence_period,
                consecutive_slots=occurrence_span,
                week_index=_week_from_row(cell.row, cell.value),
                row_index=cell.row,
                col_index=cell.col,
                sheet_name=sheet_name,
                raw_cell=cell.value,
            ))
    return result, unparsed, non_teaching


def _week_from_row(row_index: int, value: str) -> int:
    if 5 <= row_index <= 24:
        return row_index - 4
    match = re.search(r"第?([1-9]\d*)周", value)
    if match:
        return _safe_int(match.group(1))
    return 0


def _is_non_teaching_marker(value: str) -> bool:
    text = _clean(value)
    return any(marker in text for marker in NON_TEACHING_MARKERS)


def _split_period_annotation(token: str) -> tuple[str, tuple[int, int] | None]:
    """剥离形如 ``高166(9-10)`` 的子区间标注，返回 (课程代码, (起始节次, 连续节数))。

    晚间 91011 是 19:10-21:35 的三节大块，只上两节的课在格子里写成 ``(9-10)``。
    不剥离标注，课程代码就匹配不上 COURSE_CODE_PATTERN，整条记录会被静默丢弃。
    """
    match = PERIOD_ANNOTATION_PATTERN.search(token)
    if not match:
        return token, None
    code = _clean_token(PERIOD_ANNOTATION_PATTERN.sub("", token))
    start = _safe_int(match.group(1))
    end = _safe_int(match.group(2))
    if start <= 0 or end < start:
        return code, None
    return code, (start, end - start + 1)


def _parse_timetable_cell(value: str) -> list[tuple[str, str, tuple[int, int] | None]]:
    text = value.replace("\r", " ").replace("\n", " ").replace("，", " ").replace(",", " ").replace("；", " ").replace(";", " ").replace("/", " ")
    result: list[tuple[str, str, tuple[int, int] | None]] = []
    raw_tokens = [_clean_token(token) for token in re.split(r"\s+", text) if _clean_token(token)]
    tokens: list[str] = []
    overrides: list[tuple[int, int] | None] = []
    # 标注也可能单独成一个 token（例如 "(9-10) 公共体育"），此时作用于整格。
    shared_override: tuple[int, int] | None = None
    for raw_token in raw_tokens:
        code, override = _split_period_annotation(raw_token)
        if not code:
            if override:
                shared_override = override
            continue
        tokens.append(code)
        overrides.append(override)
    for index, token in enumerate(tokens):
        if _is_resource_point(token):
            continue
        if not COURSE_CODE_PATTERN.match(token):
            continue
        classroom = ""
        for next_token in tokens[index + 1:]:
            if COURSE_CODE_PATTERN.match(next_token):
                break
            if _is_importable_classroom_token(next_token):
                classroom = next_token
                break
            if _is_resource_point(next_token):
                break
        result.append((token, classroom, overrides[index] or shared_override))
    if not result and PUBLIC_PHYSICAL_EDUCATION in text:
        result.append((PUBLIC_PHYSICAL_EDUCATION, "", shared_override))
    return result


def _sheet_trace(
    *,
    sheet_name: str,
    cells: list[Cell],
    details: list[CourseDetail],
    occurrences: list[Occurrence],
    unparsed_cells: list[dict[str, Any]],
    non_teaching_cells: list[dict[str, Any]],
    detected_day_cols: dict[int, int],
    day_cols: dict[int, int],
    detected_period_rows: dict[int, int],
    period_rows: dict[int, int],
    day_period_cols: dict[int, tuple[int, int]],
    used_day_fallback: bool,
    used_period_fallback: bool,
) -> dict[str, Any]:
    occurrence_cells = {(item.row_index, item.col_index) for item in occurrences}
    detail_cells = {(item.row_index, item.col_index) for item in details}
    return {
        "sheet_name": sheet_name,
        "non_empty_cell_count": len(cells),
        "raw_cells_preview": [_cell_dict(cell) for cell in sorted(cells, key=lambda item: (item.row, item.col))[:40]],
        "layout": {
            "detected_day_columns": _int_key_map(detected_day_cols),
            "effective_day_columns": _int_key_map(day_cols),
            "detected_period_rows": _int_key_map(detected_period_rows),
            "effective_period_rows": _int_key_map(period_rows),
            "day_period_columns": {
                str(col): {"day_of_week": day, "period_index": period, "consecutive_slots": span}
                for col, (day, period, span) in sorted(day_period_cols.items())
            },
            "used_day_fallback": used_day_fallback,
            "used_period_fallback": used_period_fallback,
            "layout_mode": "day_period_columns" if day_period_cols else "day_columns_and_period_rows",
        },
        "course_detail_count": len(details),
        "course_detail_cells": sorted([{"row": row, "col": col} for row, col in detail_cells], key=lambda item: (item["row"], item["col"])),
        "occurrence_count": len(occurrences),
        "occurrence_cell_count": len(occurrence_cells),
        "unparsed_grid_cell_count": len(unparsed_cells),
        "unparsed_grid_cells_preview": unparsed_cells[:40],
        "non_teaching_grid_cell_count": len(non_teaching_cells),
        "occurrence_cells_preview": sorted([{"row": row, "col": col} for row, col in occurrence_cells], key=lambda item: (item["row"], item["col"]))[:80],
        "course_codes": sorted({item.course_code for item in occurrences}),
    }


def _build_intermediate(
    *,
    input_path: Path,
    output_dir: Path,
    workbook: dict[str, list[Cell]],
    class_meta: dict[str, Any],
    sheet_traces: list[dict[str, Any]],
    course_details: list[CourseDetail],
    occurrences: list[Occurrence],
    courses: list[dict[str, Any]],
    teachers: list[dict[str, Any]],
    classrooms: list[dict[str, Any]],
    teaching_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": "parse-intermediate-v1",
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "workbook": {
            "sheet_count": len(workbook),
            "sheets": [{"sheet_name": name, "non_empty_cell_count": len(cells)} for name, cells in workbook.items()],
        },
        "class_meta": class_meta,
        "sheets": sheet_traces,
        "course_details": [_course_detail_dict(item) for item in course_details],
        "occurrences": [_occurrence_intermediate_row(item) for item in occurrences],
        "normalized": {
            "courses": courses,
            "teachers": teachers,
            "classrooms": classrooms,
            "teaching_tasks": teaching_tasks,
        },
        "counts": {
            "course_details": len(course_details),
            "occurrences": len(occurrences),
            "courses": len(courses),
            "teachers": len(teachers),
            "classrooms": len(classrooms),
            "teaching_tasks": len(teaching_tasks),
        },
    }


def _build_quality_report(
    *,
    input_path: Path,
    output_dir: Path,
    class_meta: dict[str, Any],
    sheet_traces: list[dict[str, Any]],
    course_details: list[CourseDetail],
    details_by_code: dict[str, CourseDetail],
    occurrences: list[Occurrence],
    courses: list[dict[str, Any]],
    teaching_tasks: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    unmatched_occurrence_codes: list[str],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for field in ["class_name", "major", "department"]:
        if not _clean(class_meta.get(field)):
            issues.append(_quality_issue("missing_class_meta", "warning", f"班级元信息缺少 {field}", field=field))
    if not course_details:
        issues.append(_quality_issue("no_course_details", "error", "未识别到课程详情区"))
    if not occurrences:
        issues.append(_quality_issue("no_timetable_occurrences", "error", "未识别到任何课表格子里的课程出现记录"))

    for trace in sheet_traces:
        layout = trace.get("layout", {})
        if layout.get("used_day_fallback"):
            issues.append(_quality_issue("weekday_fallback", "warning", "星期列使用兜底识别", sheet=trace.get("sheet_name")))
        if layout.get("used_period_fallback"):
            issues.append(_quality_issue("period_fallback", "warning", "节次使用行号兜底识别", sheet=trace.get("sheet_name")))
        if trace.get("course_detail_count", 0) == 0 and trace.get("occurrence_count", 0) > 0:
            issues.append(_quality_issue("sheet_missing_course_details", "info", "sheet 有课表记录但无课程详情", sheet=trace.get("sheet_name")))
        unparsed_count = int(trace.get("unparsed_grid_cell_count", 0) or 0)
        if unparsed_count:
            # 静默丢格子是最贵的失败方式：曾经整批晚间课消失，质量分仍是 100。
            issues.append(_quality_issue(
                "unparsed_grid_cells",
                "warning",
                f"{unparsed_count} 个网格单元格未解析出任何课程记录",
                sheet=trace.get("sheet_name"),
                count=unparsed_count,
            ))

    for code in unmatched_occurrence_codes:
        issues.append(_quality_issue("occurrence_without_detail", "warning", f"课表中出现课程代码 {code}，但课程详情区未匹配", course_code=code))

    occurrence_codes = {item.course_code for item in occurrences}
    for code, detail in details_by_code.items():
        if code not in occurrence_codes and code not in UNSCHEDULABLE_COURSES:
            issues.append(_quality_issue("detail_without_occurrence", "info", f"课程详情 {code} 未在课表格子中出现", course_code=code, course_name=detail.course_name))

    courses_by_code = {str(row.get("course_code")): row for row in courses}
    for task in teaching_tasks:
        if str(task.get("schedulable")) != "true":
            continue
        course_code = str(task.get("course_code") or "")
        if not _clean(task.get("teacher_name")):
            issues.append(_quality_issue("schedulable_task_missing_teacher", "error", "可排教学任务缺少教师", course_code=course_code, course_name=task.get("course_name")))
        hours = _safe_int(task.get("total_hours"))
        if hours <= 0:
            issues.append(_quality_issue("schedulable_task_missing_hours", "error", "可排教学任务缺少有效课时", course_code=course_code, course_name=task.get("course_name")))
        elif hours > 96:
            issues.append(_quality_issue("suspicious_high_hours", "warning", f"课时异常偏高：{hours}", course_code=course_code, course_name=task.get("course_name"), total_hours=hours))
        if not _clean(task.get("required_room_type")):
            issues.append(_quality_issue("schedulable_task_missing_room_type", "warning", "可排教学任务缺少教室类型需求", course_code=course_code, course_name=task.get("course_name")))
        if course_code in occurrence_codes and not _occurrence_has_classroom(course_code, occurrences):
            issues.append(_quality_issue("occurrence_missing_classroom", "warning", "可排课程的课表片段缺少教室", course_code=course_code, course_name=task.get("course_name")))
        course = courses_by_code.get(course_code, {})
        if _clean(course.get("required_hours")) and hours != _safe_int(course.get("required_hours")):
            issues.append(_quality_issue("task_course_hour_mismatch", "warning", "教学任务课时与课程详情课时不一致", course_code=course_code))

    schedulable_codes = {
        code
        for code, course in courses_by_code.items()
        if str(course.get("schedulable")) == "true"
    }
    duplicate_slots = _duplicate_class_slots(occurrences, schedulable_codes=schedulable_codes)
    for key, bucket in duplicate_slots.items():
        issues.append(_quality_issue(
            "same_class_slot_multiple_courses",
            "warning",
            "同一班级同一周/星期/节次识别出多门课程",
            class_name=key[0],
            week_index=key[1],
            day_of_week=key[2],
            period_index=key[3],
            course_codes=sorted({item.course_code for item in bucket}),
        ))

    issue_counts = dict(Counter(issue["issue"] for issue in issues).most_common())
    severity_counts = dict(Counter(issue["severity"] for issue in issues).most_common())
    score = _quality_score(issues)
    rejected = any(issue["severity"] == "error" for issue in issues)
    review_needed = rejected or any(issue["severity"] == "warning" for issue in issues)
    return {
        "version": "parse-quality-v1",
        "status": "rejected" if rejected else ("review_needed" if review_needed else "accepted"),
        "score": score,
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "gate": {
            "accepted": not review_needed,
            "review_needed": review_needed and not rejected,
            "rejected": rejected,
        },
        "counts": {
            "sheets": len(sheet_traces),
            "course_details": len(course_details),
            "unique_course_details": len(details_by_code),
            "occurrences": len(occurrences),
            "courses": len(courses),
            "teaching_tasks": len(teaching_tasks),
            "warnings": len(warnings),
            "issues": len(issues),
        },
        "issue_counts": issue_counts,
        "severity_counts": severity_counts,
        "warnings": warnings,
        "issues": issues,
        "issues_preview": issues[:80],
        "metrics": {
            "occurrence_detail_match_rate": _ratio(len({item.course_code for item in occurrences if item.course_code in details_by_code}), len({item.course_code for item in occurrences})),
            "schedulable_task_teacher_fill_rate": _ratio(
                sum(1 for item in teaching_tasks if item.get("schedulable") == "true" and _clean(item.get("teacher_name"))),
                sum(1 for item in teaching_tasks if item.get("schedulable") == "true"),
            ),
            "occurrence_classroom_fill_rate": _ratio(sum(1 for item in occurrences if item.classroom_name), len(occurrences)),
            "layout_fallback_sheet_count": sum(1 for item in sheet_traces if item.get("layout", {}).get("used_day_fallback") or item.get("layout", {}).get("used_period_fallback")),
        },
    }


def _build_courses(code_order: list[str], details_by_code: dict[str, CourseDetail], occurrences: list[Occurrence]) -> list[dict[str, Any]]:
    rows = []
    occurrence_rooms: dict[str, set[str]] = {}
    for item in occurrences:
        if item.classroom_name:
            occurrence_rooms.setdefault(item.course_code, set()).add(item.classroom_name)
    for code in code_order:
        detail = details_by_code.get(code)
        course_name = detail.course_name if detail else code
        rooms = detail.rooms if detail else list(occurrence_rooms.get(code, []))
        teachers = detail.teachers if detail else []
        course_type = _infer_course_type(course_name, rooms)
        schedulable, exclude_reason = _schedulable_state(code, course_name, teachers=teachers, rooms=rooms)
        rows.append({
            "course_id": detail.course_id if detail else "",
            "course_code": code,
            "course_name": course_name,
            "credits": detail.credits if detail else "",
            "required_hours": detail.required_hours if detail else "",
            "course_type": course_type,
            "required_room_type": _required_room_type(course_type, schedulable),
            "schedulable": str(schedulable).lower(),
            "exclude_reason": exclude_reason,
            "raw_text": detail.raw_text if detail else "",
        })
    return rows


def _build_teachers(details_by_code: dict[str, CourseDetail]) -> list[dict[str, Any]]:
    seen: dict[str, str] = {}
    for detail in details_by_code.values():
        for teacher in detail.teachers:
            seen.setdefault(teacher, detail.raw_text)
    return [{"teacher_name": name, "department": "", "title": "", "raw_source": raw} for name, raw in sorted(seen.items())]


def _build_classrooms(details_by_code: dict[str, CourseDetail], occurrences: list[Occurrence], courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    course_type_by_code = {str(row["course_code"]): str(row["course_type"]) for row in courses}
    rooms: dict[str, set[str]] = {}
    for detail in details_by_code.values():
        for room in detail.rooms:
            if not _is_importable_classroom_token(room):
                continue
            rooms.setdefault(room, set()).add("course_detail")
    for item in occurrences:
        if item.classroom_name:
            rooms.setdefault(item.classroom_name, set()).add("timetable")
    result = []
    for room, sources in sorted(rooms.items()):
        linked_codes = {item.course_code for item in occurrences if item.classroom_name == room}
        room_type = "机房" if any(course_type_by_code.get(code) == "上机课" for code in linked_codes) else "普通教室"
        result.append({
            "classroom_name": room,
            "classroom_type": room_type,
            "capacity": 120,
            "status": "ACTIVE",
            "raw_source": "+".join(sorted(sources)),
        })
    return result


def _build_class_group(meta: dict[str, Any], class_name: str) -> dict[str, Any]:
    return {
        "class_name": class_name,
        "major": meta.get("major") or "",
        "department": meta.get("department") or "",
        "grade": meta.get("grade") or "",
        "student_count": _student_count_value(meta.get("student_count")),
        "academic_year": meta.get("academic_year") or "",
        "semester": meta.get("semester") or "",
    }


def _build_teaching_tasks(
    class_name: str,
    task_batch: str,
    courses: list[dict[str, Any]],
    details_by_code: dict[str, CourseDetail],
    occurrences: list[Occurrence],
) -> list[dict[str, Any]]:
    rows = []
    occurrence_codes = {item.course_code for item in occurrences}
    for course in courses:
        code = str(course["course_code"])
        if code not in occurrence_codes and code not in details_by_code:
            continue
        detail = details_by_code.get(code)
        teacher_names = _join_names(detail.teachers) if detail else ""
        pattern = _derive_pattern(code, occurrences)
        rows.append({
            "course_id": course.get("course_id", ""),
            "course_code": code,
            "course_name": course["course_name"],
            "teacher_name": teacher_names,
            "class_name": class_name,
            "class_names": class_name,
            "total_hours": course["required_hours"],
            "required_room_type": course["required_room_type"],
            "task_batch": task_batch,
            "schedulable": course["schedulable"],
            "exclude_reason": course["exclude_reason"],
            "source": "schedule_excel",
            **pattern,
            **_trainable_verdict(course, pattern),
        })
    return rows


def _trainable_verdict(course: dict[str, Any], pattern: dict[str, Any]) -> dict[str, str]:
    """这条任务的课表记录能不能直接当训练样本。

    只标记，不丢弃：样本仍然导出，由训练阶段决定要不要用。静默把可疑记录混进
    训练集，会让模型学到一个学校从没执行过的课表。
    """
    if str(course.get("schedulable")) != "true":
        return {"trainable": "false",
                "untrainable_reason": course.get("exclude_reason") or "课程不需要常规排课"}
    if not pattern.get("sessions_per_week"):
        return {"trainable": "false", "untrainable_reason": "课表中没有可用的授课记录"}
    declared = _safe_int(course.get("required_hours"))
    observed = _safe_int(pattern.get("observed_hours"))
    if declared and observed and declared != observed:
        return {"trainable": "false",
                "untrainable_reason": f"声明{declared}课时与课表实测{observed}课时不一致，待人工确认"}
    if pattern.get("pattern_regular") != "true":
        return {"trainable": "false", "untrainable_reason": "各周授课次数不一致，待人工确认"}
    return {"trainable": "true", "untrainable_reason": ""}


def _derive_pattern(course_code: str, occurrences: list[Occurrence]) -> dict[str, Any]:
    """从课表网格反推教学节奏。

    真实课表是"周 × 星期 × 大节"的网格，它直接说明了这门课每周上几次、连续上几周、
    一次占几节。这些事实原本被丢掉，教学任务只带 total_hours，排课引擎只能退回按
    课时查表推断（`pattern_builder` 的 fallback）。这里把它们如实记下来。

    `pattern_regular` 为 false 表示各周次数不一致（例如单双周、期中停课），
    此时 sessions_per_week 取众数，需要人工确认而不是直接采信。
    """
    mine = [item for item in occurrences if item.course_code == course_code and item.week_index > 0]
    if not mine:
        return {
            "sessions_per_week": "", "duration_weeks": "", "session_slots": "",
            "observed_hours": "", "pattern_source": "", "pattern_regular": "",
            "active_weeks": "",
        }
    per_week = Counter(item.week_index for item in mine)
    session_slots = Counter(item.consecutive_slots for item in mine).most_common(1)[0][0]
    sessions_per_week = Counter(per_week.values()).most_common(1)[0][0]
    observed_hours = sum(item.consecutive_slots for item in mine)
    return {
        "sessions_per_week": sessions_per_week,
        "duration_weeks": len(per_week),
        "session_slots": session_slots,
        "observed_hours": observed_hours,
        "pattern_source": "timetable",
        "pattern_regular": str(len(set(per_week.values())) == 1).lower(),
        "active_weeks": ",".join(str(week) for week in sorted(per_week)),
    }


def _occurrence_row(item: Occurrence, details_by_code: dict[str, CourseDetail]) -> dict[str, Any]:
    detail = details_by_code.get(item.course_code)
    return {
        "class_name": item.class_name,
        "course_id": detail.course_id if detail else "",
        "course_code": item.course_code,
        "course_name": detail.course_name if detail else item.course_code,
        "teacher_name": _join_names(detail.teachers) if detail else "",
        "classroom_name": item.classroom_name,
        "day_of_week": item.day_of_week,
        "period_index": item.period_index,
        "consecutive_slots": item.consecutive_slots,
        "week_index": item.week_index,
        "row_index": item.row_index,
        "col_index": item.col_index,
        "sheet_name": item.sheet_name,
        "raw_cell": item.raw_cell,
    }


def _ordered_codes(occurrences: list[Occurrence], details_by_code: dict[str, CourseDetail]) -> list[str]:
    result: list[str] = []
    seen = set()
    for item in occurrences:
        if item.course_code not in seen:
            seen.add(item.course_code)
            result.append(item.course_code)
    return result


def _infer_course_type(course_name: str, rooms: list[str]) -> str:
    if any(keyword in course_name for keyword in ["实验", "上机", "实训", "程序设计", "数据库应用"]):
        return "上机课"
    return "理论课"


def _required_room_type(course_type: str, schedulable: bool) -> str:
    if not schedulable:
        return ""
    return "机房" if course_type == "上机课" else "普通教室"


def _schedulable_state(course_code: str, course_name: str, *, teachers: list[str] | None = None, rooms: list[str] | None = None) -> tuple[bool, str]:
    # Exact match on course codes/names known to be unschedulable
    if course_code in UNSCHEDULABLE_COURSES or course_name in UNSCHEDULABLE_COURSES:
        return False, "公共体育暂不进入当前排课引擎"

    if any(course_code.startswith(prefix) for prefix in UNSCHEDULABLE_CODE_PREFIXES):
        return False, f"课程代码 {course_code} 属于特殊课程，不参与排课"

    # Virtual/reserved courses (code starts with XN or name contains 虚拟)
    code_upper = (course_code or "").upper()
    if code_upper.startswith("XN") or "虚拟" in course_name:
        return False, "虚拟课不参与排课"

    if any("虚拟" in teacher for teacher in (teachers or [])):
        return False, "虚拟教师课程不参与排课"

    if any(_is_resource_point(room) or "虚拟" in room for room in (rooms or [])):
        return False, "虚拟资源点课程不参与排课"

    # Physical education courses
    if any(kw in course_name for kw in PE_KEYWORDS):
        return False, "体育课由体育部统一安排，不参与排课"

    # Other special course types
    if any(kw in course_name for kw in UNSCHEDULABLE_KEYWORDS):
        return False, f"特殊课程（{course_name}）暂不参与排课"

    return True, ""


def _should_drop_course_detail(detail: CourseDetail, class_name: str) -> bool:
    if not _is_valid_course_name(detail.course_name):
        return True
    if not _has_valid_training_hours(detail.required_hours):
        return True
    return _has_import_blocker(
        class_name=class_name,
        course_code=detail.course_code,
        course_name=detail.course_name,
        teacher_names=detail.teachers,
        classroom_names=detail.rooms,
    )


def _should_drop_occurrence(
    item: Occurrence,
    detail: CourseDetail | None,
    dropped_detail_codes: set[str],
) -> bool:
    if item.course_code in dropped_detail_codes:
        return True
    if not item.classroom_name:
        return True
    if _contains_blocked_keyword(item.raw_cell):
        return True
    return _has_import_blocker(
        class_name=item.class_name,
        course_code=item.course_code,
        course_name=detail.course_name if detail else item.course_code,
        teacher_names=detail.teachers if detail else [],
        classroom_names=[item.classroom_name] if item.classroom_name else _raw_cell_location_tokens(item.raw_cell),
    )


def _has_import_blocker(
    *,
    class_name: str,
    course_code: str,
    course_name: str,
    teacher_names: list[str],
    classroom_names: list[str],
) -> bool:
    if _is_special_course(course_code, course_name):
        return True
    if _contains_blocked_keyword(course_code) or _contains_blocked_keyword(course_name):
        return True
    if _contains_blocked_keyword(class_name):
        return True
    if any(_contains_blocked_keyword(name) for name in teacher_names):
        return True
    return any(_is_blocked_classroom_token(name) for name in classroom_names if name)


def _is_special_course(course_code: str, course_name: str) -> bool:
    if course_code in UNSCHEDULABLE_COURSES or course_name in UNSCHEDULABLE_COURSES:
        return True
    if course_code in BLOCKED_IMPORT_TOKENS or course_name in BLOCKED_IMPORT_TOKENS:
        return True
    if any(course_code.startswith(prefix) for prefix in UNSCHEDULABLE_CODE_PREFIXES):
        return True
    code_upper = (course_code or "").upper()
    if code_upper.startswith("XN") or "虚拟" in course_name:
        return True
    if any(keyword in course_name for keyword in PE_KEYWORDS):
        return True
    return any(keyword in course_name for keyword in UNSCHEDULABLE_KEYWORDS)


def _contains_blocked_keyword(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "虚拟" in text or "未排地点" in text:
        return True
    if any(token in text for token in BLOCKED_IMPORT_TOKENS):
        return True
    return any(keyword in text for keyword in UNSCHEDULABLE_KEYWORDS)


def _is_blocked_classroom_token(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if _contains_blocked_keyword(text) or _is_resource_point(text):
        return True
    return not _is_importable_classroom_token(text)


def _raw_cell_location_tokens(value: str) -> list[str]:
    tokens = [_clean_token(token) for token in re.split(r"[\s,，;；/]+", value or "") if _clean_token(token)]
    return [
        token
        for token in tokens
        if not COURSE_CODE_PATTERN.match(token) and token != PUBLIC_PHYSICAL_EDUCATION
    ]


def _is_classroom_token(value: str) -> bool:
    return bool(CLASSROOM_PATTERN.match(value) or _is_resource_point(value))


def _is_importable_classroom_token(value: str) -> bool:
    return bool(CLASSROOM_PATTERN.match(value))


def _is_resource_point(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if (
        RESOURCE_POINT_PATTERN.match(text)
        or LETTER_RESOURCE_POINT_PATTERN.match(text)
        or VIRTUAL_RESOURCE_POINT_PATTERN.match(text)
        or CLASS_LAB_RESOURCE_POINT_PATTERN.match(text)
    ):
        return True
    return any(keyword in text for keyword in RESOURCE_POINT_KEYWORDS)


def _cell_dict(cell: Cell) -> dict[str, Any]:
    return {"row": cell.row, "col": cell.col, "value": cell.value}


def _course_detail_dict(detail: CourseDetail) -> dict[str, Any]:
    return asdict(detail)


def _occurrence_intermediate_row(item: Occurrence) -> dict[str, Any]:
    return asdict(item)


def _int_key_map(values: dict[int, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in sorted(values.items())}


def _quality_issue(issue: str, severity: str, message: str, **details: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "issue": issue,
        "severity": severity,
        "message": message,
    }
    row.update({key: value for key, value in details.items() if value not in (None, "", [])})
    return row


def _quality_score(issues: list[dict[str, Any]]) -> int:
    penalties = {"error": 35, "warning": 12, "info": 3}
    score = 100
    for issue in issues:
        score -= penalties.get(str(issue.get("severity")), 0)
    return max(0, score)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _occurrence_has_classroom(course_code: str, occurrences: list[Occurrence]) -> bool:
    return any(item.course_code == course_code and bool(item.classroom_name) for item in occurrences)


def _duplicate_class_slots(
    occurrences: list[Occurrence],
    *,
    schedulable_codes: set[str],
) -> dict[tuple[str, int, int, int], list[Occurrence]]:
    buckets: dict[tuple[str, int, int, int], list[Occurrence]] = defaultdict(list)
    for item in occurrences:
        if item.course_code not in schedulable_codes:
            continue
        key = (item.class_name, item.week_index, item.day_of_week, item.period_index)
        buckets[key].append(item)
    return {
        key: bucket
        for key, bucket in buckets.items()
        if len({item.course_code for item in bucket}) > 1
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _split_list(value: str) -> list[str]:
    return [_clean_token(item) for item in re.split(r"[,，、/;；\s]+", value or "") if _clean_token(item)]


def _join_names(values: list[str]) -> str:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return ",".join(result)


# 课程说明是一整行连排的：`…室[08202]【专】48人     游戏策划与运营(游248)…`。
# `【专】48人` 是上一门课的班型与人数标注，会粘到下一门课的名字前面。
_NAME_PREFIX_NOISE = re.compile(r"^(?:【[^】]{1,6}】|\d+人|[，,;；、\s])+")


def _clean_course_name(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").strip(" ，,;；")
    return _NAME_PREFIX_NOISE.sub("", text)


def _is_valid_course_name(value: str) -> bool:
    text = _clean_course_name(value)
    if len(text) < 2:
        return False
    if not re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", text):
        return False
    return not COURSE_CODE_PATTERN.fullmatch(text)


def _has_valid_training_hours(value: Any) -> bool:
    hours = _safe_int(value)
    return hours > 0 and hours % 2 == 0


def _clean_token(value: str) -> str:
    return str(value or "").strip().strip("，,;；:：")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _infer_grade(class_name: str) -> str:
    match = re.search(r"(20\d{2})级", class_name or "")
    return match.group(1) if match else ""


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _student_count_value(value: Any) -> int | str:
    count = _safe_int(value)
    return count if count > 0 else ""


def _col_to_index(col: str) -> int:
    result = 0
    for char in col:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse one class schedule .xlsx into CSV files.")
    parser.add_argument("--input", required=True, help="Path to .xlsx class schedule file")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--class-name", default=None)
    parser.add_argument("--major", default=None)
    parser.add_argument("--department", default=None)
    parser.add_argument("--grade", default=None)
    parser.add_argument("--student-count", type=int, default=None)
    parser.add_argument("--task-batch", default="DEFAULT")
    args = parser.parse_args()
    report = parse_schedule_excel(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        class_name=args.class_name,
        major=args.major,
        department=args.department,
        grade=args.grade,
        student_count=args.student_count,
        task_batch=args.task_batch,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
