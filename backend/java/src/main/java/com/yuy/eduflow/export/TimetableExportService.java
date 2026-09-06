package com.yuy.eduflow.export;

import com.yuy.eduflow.assignment.CourseAssignmentHourAuditResult;
import com.yuy.eduflow.assignment.CourseAssignmentService;
import com.yuy.eduflow.assignment.CourseAssignmentTaskHourAudit;
import com.yuy.eduflow.assignment.CourseAssignmentView;
import com.yuy.eduflow.assignment.TimetableQuery;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import org.apache.poi.ss.usermodel.BorderStyle;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellStyle;
import org.apache.poi.ss.usermodel.FillPatternType;
import org.apache.poi.ss.usermodel.Font;
import org.apache.poi.ss.usermodel.HorizontalAlignment;
import org.apache.poi.ss.usermodel.IndexedColors;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.VerticalAlignment;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.util.WorkbookUtil;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;

/**
 * 多角色课表导出。
 *
 * <p>一条正式安排占用 {@code consecutive_slots} 个 45 分钟原子节次，导出必须把整段展开，
 * 不能只在起始节次画一格。周次不固定为整学期：同一格在不同周可能是不同课程，因此格子里
 * 显式写出该课的生效周集合，而不是假设一张周课表覆盖全学期。</p>
 */
@Service
public class TimetableExportService {

	/** 一个工作簿里最多生成多少张角色分表；超过说明筛选条件太宽，应先收窄。 */
	static final int MAX_ENTITY_SHEETS = 60;

	private static final String[] DAY_NAMES = {"周一", "周二", "周三", "周四", "周五", "周六", "周日"};

	private final CourseAssignmentService courseAssignmentService;

	public TimetableExportService(CourseAssignmentService courseAssignmentService) {
		this.courseAssignmentService = courseAssignmentService;
	}

	public TimetableExport export(TimetableExportRole role, TimetableQuery query) {
		List<CourseAssignmentView> rows = courseAssignmentService.findViews(query);
		try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
			Styles styles = new Styles(workbook);
			writeCoverSheet(workbook, styles, role, query, rows);
			if (role == TimetableExportRole.REGISTRAR) {
				writeDetailSheet(workbook, styles, rows);
				writeHourLedgerSheet(workbook, styles, query.allocationTaskId());
			} else {
				writeEntitySheets(workbook, styles, role, rows);
				writeDetailSheet(workbook, styles, rows);
			}
			workbook.write(out);
			return new TimetableExport(fileName(role), out.toByteArray());
		} catch (IOException ex) {
			throw new UncheckedIOException(ex);
		}
	}

	private String fileName(TimetableExportRole role) {
		return role.label() + "-" + LocalDate.now() + ".xlsx";
	}

	// ---- 说明页 ----------------------------------------------------------

	private void writeCoverSheet(Workbook workbook, Styles styles, TimetableExportRole role,
		TimetableQuery query, List<CourseAssignmentView> rows) {
		Sheet sheet = workbook.createSheet("导出说明");
		sheet.setColumnWidth(0, 22 * 256);
		sheet.setColumnWidth(1, 60 * 256);
		int r = 0;
		r = keyValue(sheet, styles, r, "导出视角", role.label());
		r = keyValue(sheet, styles, r, "导出时间", LocalDate.now().toString());
		r = keyValue(sheet, styles, r, "记录条数", String.valueOf(rows.size()));
		r = keyValue(sheet, styles, r, "占用原子课时", String.valueOf(totalAtomicPeriods(rows)));
		r = keyValue(sheet, styles, r, "筛选条件", describeFilters(query));
		r = keyValue(sheet, styles, r, "时间坐标",
			"每天 10 个 45 分钟原子节次：上午 1-4、下午 5-8、晚上 9-10");
		r = keyValue(sheet, styles, r, "说明",
			"一次授课按连续节数整段占用；续占节次在表中以 ↳ 标记。晚间与周末为人工保留时段，"
				+ "自动排课不会使用，人工调课可以显式使用。");
		keyValue(sheet, styles, r, "周次口径",
			"格子内的周次是该次课实际生效的绝对周集合，不同周可能对应不同课程。");
	}

	private int keyValue(Sheet sheet, Styles styles, int rowIndex, String key, String value) {
		Row row = sheet.createRow(rowIndex);
		Cell keyCell = row.createCell(0);
		keyCell.setCellValue(key);
		keyCell.setCellStyle(styles.header);
		Cell valueCell = row.createCell(1);
		valueCell.setCellValue(value);
		valueCell.setCellStyle(styles.wrapped);
		return rowIndex + 1;
	}

	private String describeFilters(TimetableQuery query) {
		List<String> parts = new ArrayList<>();
		if (query.allocationTaskId() != null) {
			parts.add("排课任务=" + query.allocationTaskId());
		}
		if (query.teacherId() != null) {
			parts.add("教师=" + query.teacherId());
		}
		if (query.classGroupId() != null) {
			parts.add("班级=" + query.classGroupId());
		}
		if (query.courseId() != null) {
			parts.add("课程=" + query.courseId());
		}
		if (query.classroomId() != null) {
			parts.add("教室=" + query.classroomId());
		}
		if (query.weekNumber() != null) {
			parts.add("周次=" + query.weekNumber());
		}
		if (query.dayOfWeek() != null) {
			parts.add("星期=" + query.dayOfWeek());
		}
		if (query.status() != null && !query.status().isBlank()) {
			parts.add("状态=" + query.status());
		}
		return parts.isEmpty() ? "全部生效中的正式课表" : String.join("；", parts);
	}

	private int totalAtomicPeriods(List<CourseAssignmentView> rows) {
		return rows.stream().mapToInt(this::span).sum();
	}

	// ---- 角色分表 --------------------------------------------------------

	private void writeEntitySheets(Workbook workbook, Styles styles, TimetableExportRole role,
		List<CourseAssignmentView> rows) {
		Map<String, Entity> entities = collectEntities(role, rows);
		if (entities.size() > MAX_ENTITY_SHEETS) {
			throw new ValidationException(String.format(
				"当前条件会生成 %d 张%s，超过单个工作簿上限 %d 张；请先按教师、班级、教室、课程或排课任务收窄筛选条件",
				entities.size(), role.label(), MAX_ENTITY_SHEETS));
		}
		if (entities.isEmpty()) {
			Sheet empty = workbook.createSheet(role.label());
			empty.createRow(0).createCell(0).setCellValue("当前筛选条件下没有正式课表记录");
			return;
		}
		for (Entity entity : entities.values()) {
			writeGridSheet(workbook, styles, role, entity);
		}
	}

	private Map<String, Entity> collectEntities(TimetableExportRole role, List<CourseAssignmentView> rows) {
		Map<String, Entity> entities = new LinkedHashMap<>();
		for (CourseAssignmentView row : rows) {
			for (EntityRef ref : referencesOf(role, row)) {
				entities.computeIfAbsent(ref.key(), key -> new Entity(ref.name())).rows.add(row);
			}
		}
		return entities;
	}

	private List<EntityRef> referencesOf(TimetableExportRole role, CourseAssignmentView row) {
		List<EntityRef> refs = new ArrayList<>();
		switch (role) {
			case TEACHER -> {
				if (row.getPrimaryTeacherId() != null) {
					refs.add(new EntityRef("T" + row.getPrimaryTeacherId(), row.getPrimaryTeacherName()));
				}
				if (row.getAssistantTeacherId() != null) {
					refs.add(new EntityRef("T" + row.getAssistantTeacherId(), row.getAssistantTeacherName()));
				}
			}
			case CLASS -> {
				String[] ids = splitCsv(row.getClassGroupIds());
				String[] names = splitList(row.getClassGroupName());
				for (int i = 0; i < ids.length; i++) {
					String name = i < names.length ? names[i] : ids[i];
					refs.add(new EntityRef("C" + ids[i], name));
				}
			}
			case CLASSROOM -> {
				if (row.getClassroomId() != null) {
					refs.add(new EntityRef("R" + row.getClassroomId(), row.getClassroomName()));
				}
			}
			case REGISTRAR -> {
			}
		}
		return refs;
	}

	private void writeGridSheet(Workbook workbook, Styles styles, TimetableExportRole role, Entity entity) {
		Sheet sheet = workbook.createSheet(uniqueSheetName(workbook, entity.name));
		sheet.setColumnWidth(0, 14 * 256);
		for (int day = 1; day <= SchedulingTimePolicy.DAYS_PER_WEEK; day++) {
			sheet.setColumnWidth(day, 30 * 256);
		}

		Row title = sheet.createRow(0);
		Cell titleCell = title.createCell(0);
		titleCell.setCellValue(role.label() + "：" + entity.name);
		titleCell.setCellStyle(styles.title);

		Row header = sheet.createRow(1);
		Cell corner = header.createCell(0);
		corner.setCellValue("节次");
		corner.setCellStyle(styles.header);
		for (int day = 1; day <= SchedulingTimePolicy.DAYS_PER_WEEK; day++) {
			Cell cell = header.createCell(day);
			cell.setCellValue(DAY_NAMES[day - 1]);
			cell.setCellStyle(day > SchedulingTimePolicy.WEEKDAY_LAST ? styles.reservedHeader : styles.header);
		}

		Map<Integer, Map<Integer, List<String>>> grid = buildGrid(role, entity.rows);
		for (int period = SchedulingTimePolicy.FIRST_PERIOD; period <= SchedulingTimePolicy.LAST_PERIOD; period++) {
			Row row = sheet.createRow(period + 1);
			row.setHeightInPoints(58);
			Cell label = row.createCell(0);
			label.setCellValue("第" + period + "节 · " + periodSection(period));
			label.setCellStyle(SchedulingTimePolicy.isEvening(period) ? styles.reservedHeader : styles.header);
			for (int day = 1; day <= SchedulingTimePolicy.DAYS_PER_WEEK; day++) {
				Cell cell = row.createCell(day);
				List<String> texts = grid.getOrDefault(period, Map.of()).get(day);
				cell.setCellValue(texts == null ? "" : String.join("\n\n", texts));
				cell.setCellStyle(styles.cell);
			}
		}
	}

	/** period -> day -> 该格的全部文本块（同一格在不同周可能有不同课程）。 */
	private Map<Integer, Map<Integer, List<String>>> buildGrid(TimetableExportRole role,
		List<CourseAssignmentView> rows) {
		Map<String, Session> sessions = new LinkedHashMap<>();
		for (CourseAssignmentView row : rows) {
			String key = String.join("|",
				String.valueOf(row.getDayOfWeek()),
				String.valueOf(row.getPeriodIndex()),
				String.valueOf(span(row)),
				String.valueOf(row.getTeachingTaskId()),
				String.valueOf(row.getClassroomId()));
			sessions.computeIfAbsent(key, ignored -> new Session(row)).weeks.add(row.getWeekNumber());
		}

		Map<Integer, Map<Integer, List<String>>> grid = new LinkedHashMap<>();
		List<Session> ordered = new ArrayList<>(sessions.values());
		ordered.sort(Comparator
			.comparing((Session s) -> s.head.getDayOfWeek())
			.thenComparing(s -> s.head.getPeriodIndex()));
		for (Session session : ordered) {
			CourseAssignmentView head = session.head;
			int start = head.getPeriodIndex();
			int length = span(head);
			int end = Math.min(SchedulingTimePolicy.LAST_PERIOD, start + length - 1);
			String weeks = compressWeeks(session.weeks);
			cellsOf(grid, start, head.getDayOfWeek()).add(describe(role, head, start, end, weeks));
			for (int period = start + 1; period <= end; period++) {
				cellsOf(grid, period, head.getDayOfWeek())
					.add("↳ " + head.getCourseName() + "（第" + start + "–" + end + "节 · 第" + weeks + "周）");
			}
		}
		return grid;
	}

	private List<String> cellsOf(Map<Integer, Map<Integer, List<String>>> grid, int period, int day) {
		return grid.computeIfAbsent(period, ignored -> new LinkedHashMap<>())
			.computeIfAbsent(day, ignored -> new ArrayList<>());
	}

	private String describe(TimetableExportRole role, CourseAssignmentView row, int start, int end, String weeks) {
		List<String> lines = new ArrayList<>();
		lines.add(row.getCourseName());
		if (role != TimetableExportRole.TEACHER) {
			lines.add("教师：" + row.getTeacherName());
		}
		if (role != TimetableExportRole.CLASS) {
			lines.add("班级：" + nullToDash(row.getClassGroupName()));
		}
		if (role != TimetableExportRole.CLASSROOM) {
			lines.add("教室：" + nullToDash(row.getClassroomName()));
		}
		lines.add("第" + start + "–" + end + "节 · 连续" + (end - start + 1) + "节");
		lines.add("第" + weeks + "周");
		return String.join("\n", lines);
	}

	// ---- 明细与课时总账 --------------------------------------------------

	private void writeDetailSheet(Workbook workbook, Styles styles, List<CourseAssignmentView> rows) {
		Sheet sheet = workbook.createSheet("明细");
		String[] headers = {"ID", "课程", "教学任务", "主讲教师", "助教", "班级", "教室",
			"周次", "星期", "起始节次", "连续节数", "结束节次", "来源方案", "状态"};
		Row header = sheet.createRow(0);
		for (int i = 0; i < headers.length; i++) {
			Cell cell = header.createCell(i);
			cell.setCellValue(headers[i]);
			cell.setCellStyle(styles.header);
		}
		int r = 1;
		for (CourseAssignmentView row : rows) {
			Row data = sheet.createRow(r++);
			int start = row.getPeriodIndex() == null ? 0 : row.getPeriodIndex();
			int length = span(row);
			int c = 0;
			data.createCell(c++).setCellValue(value(row.getId()));
			data.createCell(c++).setCellValue(nullToDash(row.getCourseName()));
			data.createCell(c++).setCellValue(value(row.getTeachingTaskId()));
			data.createCell(c++).setCellValue(nullToDash(row.getPrimaryTeacherName()));
			data.createCell(c++).setCellValue(nullToDash(row.getAssistantTeacherName()));
			data.createCell(c++).setCellValue(nullToDash(row.getClassGroupName()));
			data.createCell(c++).setCellValue(nullToDash(row.getClassroomName()));
			data.createCell(c++).setCellValue(value(row.getWeekNumber()));
			data.createCell(c++).setCellValue(dayName(row.getDayOfWeek()));
			data.createCell(c++).setCellValue(start);
			data.createCell(c++).setCellValue(length);
			data.createCell(c++).setCellValue(start + length - 1);
			data.createCell(c++).setCellValue(value(row.getSourceSchemeId()));
			data.createCell(c).setCellValue(row.getStatus() == null ? "-" : row.getStatus().name());
		}
		for (int i = 0; i < headers.length; i++) {
			sheet.autoSizeColumn(i);
		}
	}

	private void writeHourLedgerSheet(Workbook workbook, Styles styles, Long allocationTaskId) {
		CourseAssignmentHourAuditResult audit = courseAssignmentService.findHourAudit(allocationTaskId, null);
		Sheet sheet = workbook.createSheet("课时总账");
		int r = 0;
		r = keyValue(sheet, styles, r, "应排总课时", String.valueOf(audit.requiredTotalHours()));
		r = keyValue(sheet, styles, r, "已排总课时", String.valueOf(audit.scheduledTotalHours()));
		r = keyValue(sheet, styles, r, "差值", String.valueOf(audit.deltaTotalHours()));
		r = keyValue(sheet, styles, r, "课时异常任务数", String.valueOf(audit.mismatchTaskCount()));
		r++;

		String[] headers = {"教学任务", "课程", "应排课时", "已排课时", "差值", "状态"};
		Row header = sheet.createRow(r++);
		for (int i = 0; i < headers.length; i++) {
			Cell cell = header.createCell(i);
			cell.setCellValue(headers[i]);
			cell.setCellStyle(styles.header);
		}
		for (CourseAssignmentTaskHourAudit task : audit.tasks()) {
			Row data = sheet.createRow(r++);
			data.createCell(0).setCellValue(value(task.getTeachingTaskId()));
			data.createCell(1).setCellValue(nullToDash(task.getCourseName()));
			data.createCell(2).setCellValue(value(task.getRequiredHours()));
			data.createCell(3).setCellValue(value(task.getScheduledHours()));
			data.createCell(4).setCellValue(value(task.getDeltaHours()));
			data.createCell(5).setCellValue(nullToDash(task.getStatus()));
		}
		for (int i = 0; i < headers.length; i++) {
			sheet.autoSizeColumn(i);
		}
	}

	// ---- 小工具 ----------------------------------------------------------

	private int span(CourseAssignmentView row) {
		Integer slots = row.getConsecutiveSlots();
		return slots == null || slots < 1 ? 1 : slots;
	}

	private String periodSection(int period) {
		if (period <= SchedulingTimePolicy.MORNING_LAST_PERIOD) {
			return "上午";
		}
		return period <= SchedulingTimePolicy.AFTERNOON_LAST_PERIOD ? "下午" : "晚上";
	}

	private String dayName(Integer dayOfWeek) {
		if (dayOfWeek == null || dayOfWeek < 1 || dayOfWeek > DAY_NAMES.length) {
			return "-";
		}
		return DAY_NAMES[dayOfWeek - 1];
	}

	/** 把周次集合压成 "1-6"、"1-3,5,7-9" 这样的紧凑写法。 */
	static String compressWeeks(TreeSet<Integer> weeks) {
		if (weeks.isEmpty()) {
			return "-";
		}
		StringBuilder out = new StringBuilder();
		Integer rangeStart = null;
		Integer previous = null;
		for (Integer week : weeks) {
			if (rangeStart == null) {
				rangeStart = week;
			} else if (week != previous + 1) {
				appendRange(out, rangeStart, previous);
				rangeStart = week;
			}
			previous = week;
		}
		appendRange(out, rangeStart, previous);
		return out.toString();
	}

	private static void appendRange(StringBuilder out, Integer start, Integer end) {
		if (!out.isEmpty()) {
			out.append(',');
		}
		out.append(start.intValue() == end.intValue() ? String.valueOf(start) : start + "-" + end);
	}

	private String[] splitCsv(String raw) {
		return raw == null || raw.isBlank() ? new String[0] : raw.split("\\s*,\\s*");
	}

	private String[] splitList(String raw) {
		return raw == null || raw.isBlank() ? new String[0] : raw.split("\\s*[,、]\\s*");
	}

	private String nullToDash(String raw) {
		return raw == null || raw.isBlank() ? "-" : raw;
	}

	private double value(Number number) {
		return number == null ? 0 : number.doubleValue();
	}

	private String uniqueSheetName(Workbook workbook, String preferred) {
		String base = WorkbookUtil.createSafeSheetName(preferred == null || preferred.isBlank() ? "未命名" : preferred);
		String candidate = base;
		int suffix = 2;
		while (workbook.getSheet(candidate) != null) {
			String tail = "(" + suffix++ + ")";
			candidate = base.length() + tail.length() > 31
				? base.substring(0, 31 - tail.length()) + tail
				: base + tail;
		}
		return candidate;
	}

	private static final class Entity {
		private final String name;
		private final List<CourseAssignmentView> rows = new ArrayList<>();

		private Entity(String name) {
			this.name = name;
		}
	}

	private record EntityRef(String key, String name) {
	}

	private static final class Session {
		private final CourseAssignmentView head;
		private final TreeSet<Integer> weeks = new TreeSet<>();

		private Session(CourseAssignmentView head) {
			this.head = head;
		}
	}

	private static final class Styles {
		private final CellStyle title;
		private final CellStyle header;
		private final CellStyle reservedHeader;
		private final CellStyle cell;
		private final CellStyle wrapped;

		private Styles(Workbook workbook) {
			Font titleFont = workbook.createFont();
			titleFont.setBold(true);
			titleFont.setFontHeightInPoints((short) 14);
			title = workbook.createCellStyle();
			title.setFont(titleFont);

			Font headerFont = workbook.createFont();
			headerFont.setBold(true);
			header = workbook.createCellStyle();
			header.setFont(headerFont);
			header.setAlignment(HorizontalAlignment.CENTER);
			header.setVerticalAlignment(VerticalAlignment.CENTER);
			header.setFillForegroundColor(IndexedColors.GREY_25_PERCENT.getIndex());
			header.setFillPattern(FillPatternType.SOLID_FOREGROUND);
			border(header);

			reservedHeader = workbook.createCellStyle();
			reservedHeader.cloneStyleFrom(header);
			reservedHeader.setFillForegroundColor(IndexedColors.LEMON_CHIFFON.getIndex());
			reservedHeader.setFillPattern(FillPatternType.SOLID_FOREGROUND);

			cell = workbook.createCellStyle();
			cell.setWrapText(true);
			cell.setVerticalAlignment(VerticalAlignment.TOP);
			border(cell);

			wrapped = workbook.createCellStyle();
			wrapped.setWrapText(true);
			wrapped.setVerticalAlignment(VerticalAlignment.TOP);
		}

		private void border(CellStyle style) {
			style.setBorderTop(BorderStyle.THIN);
			style.setBorderBottom(BorderStyle.THIN);
			style.setBorderLeft(BorderStyle.THIN);
			style.setBorderRight(BorderStyle.THIN);
		}
	}
}
