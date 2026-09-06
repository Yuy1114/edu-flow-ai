package com.yuy.eduflow.export;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.assignment.CourseAssignmentHourAuditResult;
import com.yuy.eduflow.assignment.CourseAssignmentService;
import com.yuy.eduflow.assignment.CourseAssignmentView;
import com.yuy.eduflow.assignment.TimetableQuery;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.AssignmentStatus;
import java.io.ByteArrayInputStream;
import java.util.ArrayList;
import java.util.List;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class TimetableExportServiceTest {
	@Mock private CourseAssignmentService courseAssignmentService;
	@InjectMocks private TimetableExportService service;

	private CourseAssignmentView view(long id, int week, int day, int period, int slots,
		long taskId, long primaryTeacherId, String primaryName, Long assistantId, String assistantName,
		String classGroupIds, String classGroupNames, long classroomId, String classroomName, String courseName) {
		CourseAssignmentView view = new CourseAssignmentView();
		view.setId(id);
		view.setTeachingTaskId(taskId);
		view.setCourseName(courseName);
		view.setPrimaryTeacherId(primaryTeacherId);
		view.setPrimaryTeacherName(primaryName);
		view.setAssistantTeacherId(assistantId);
		view.setAssistantTeacherName(assistantName);
		view.setTeacherName(assistantName == null ? primaryName : primaryName + "、" + assistantName);
		view.setClassGroupIds(classGroupIds);
		view.setClassGroupName(classGroupNames);
		view.setClassroomId(classroomId);
		view.setClassroomName(classroomName);
		view.setWeekNumber(week);
		view.setDayOfWeek(day);
		view.setPeriodIndex(period);
		view.setConsecutiveSlots(slots);
		view.setStatus(AssignmentStatus.ACTIVE);
		return view;
	}

	/** 一门理论课，周一第 3-4 节，第 1-3 周，主讲 + 助教，双班。 */
	private List<CourseAssignmentView> theoryWeeks1To3() {
		List<CourseAssignmentView> rows = new ArrayList<>();
		for (int week = 1; week <= 3; week++) {
			rows.add(view(week, week, 1, 3, 2, 100L, 7L, "主讲老师", 8L, "助教老师",
				"11,12", "软工1班, 软工2班", 21L, "A101", "软件工程导论"));
		}
		return rows;
	}

	private Workbook read(byte[] content) throws Exception {
		return new XSSFWorkbook(new ByteArrayInputStream(content));
	}

	@Test
	void teacherSheetsCoverTheAssistantNotOnlyThePrimary() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(theoryWeeks1To3());

		TimetableExport export = service.export(TimetableExportRole.TEACHER, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			assertNotNull(workbook.getSheet("主讲老师"));
			assertNotNull(workbook.getSheet("助教老师"), "助教必须有自己的课表，不能被算进主讲名下");
		}
	}

	@Test
	void classSheetsCoverEveryClassOfACombinedTask() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(theoryWeeks1To3());

		TimetableExport export = service.export(TimetableExportRole.CLASS, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			assertNotNull(workbook.getSheet("软工1班"));
			assertNotNull(workbook.getSheet("软工2班"), "合班的第二个班级不能丢");
		}
	}

	@Test
	void aSessionOccupiesEveryAtomicPeriodOfItsSpan() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(theoryWeeks1To3());

		TimetableExport export = service.export(TimetableExportRole.TEACHER, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			Sheet sheet = workbook.getSheet("主讲老师");
			// 行 0 是标题，行 1 是表头，第 N 节在第 N+1 行；周一是第 1 列。
			String startCell = sheet.getRow(4).getCell(1).getStringCellValue();
			String continuationCell = sheet.getRow(5).getCell(1).getStringCellValue();
			assertTrue(startCell.contains("软件工程导论"), startCell);
			assertTrue(startCell.contains("第3–4节"), startCell);
			assertTrue(continuationCell.startsWith("↳"), "第4节必须标记为续占，不能是空格子：" + continuationCell);
			assertTrue(sheet.getRow(3).getCell(1).getStringCellValue().isEmpty(), "第2节不该被占用");
		}
	}

	@Test
	void repeatedWeeksCollapseIntoOneCellWithACompactWeekRange() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(theoryWeeks1To3());

		TimetableExport export = service.export(TimetableExportRole.TEACHER, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			String cell = workbook.getSheet("主讲老师").getRow(4).getCell(1).getStringCellValue();
			assertTrue(cell.contains("第1-3周"), "三周同一节课应压成一个区间：" + cell);
			assertEquals(1, cell.split("软件工程导论", -1).length - 1, "同一格不该重复三遍：" + cell);
		}
	}

	@Test
	void differentCoursesInDifferentWeeksShareOneCell() throws Exception {
		List<CourseAssignmentView> rows = new ArrayList<>(theoryWeeks1To3());
		rows.add(view(90L, 9, 1, 3, 2, 200L, 7L, "主讲老师", null, null,
			"11", "软工1班", 21L, "A101", "数据结构"));
		when(courseAssignmentService.findViews(any())).thenReturn(rows);

		TimetableExport export = service.export(TimetableExportRole.TEACHER, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			String cell = workbook.getSheet("主讲老师").getRow(4).getCell(1).getStringCellValue();
			assertTrue(cell.contains("软件工程导论"), cell);
			assertTrue(cell.contains("数据结构"), "同一格在不同周的另一门课不能被覆盖掉：" + cell);
			assertTrue(cell.contains("第9周"), cell);
		}
	}

	@Test
	void theWeekendAndEveningReserveStillAppearInTheGrid() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(List.of(
			view(1L, 18, 7, 10, 1, 100L, 7L, "主讲老师", null, null,
				"11", "软工1班", 21L, "A101", "补课")));

		TimetableExport export = service.export(TimetableExportRole.TEACHER, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			Sheet sheet = workbook.getSheet("主讲老师");
			assertEquals("周日", sheet.getRow(1).getCell(7).getStringCellValue());
			assertTrue(sheet.getRow(11).getCell(7).getStringCellValue().contains("补课"),
				"人工使用的周日第10节必须导出得出来");
		}
	}

	@Test
	void registrarWorkbookCarriesTheDetailAndTheHourLedger() throws Exception {
		when(courseAssignmentService.findViews(any())).thenReturn(theoryWeeks1To3());
		when(courseAssignmentService.findHourAudit(null, null))
			.thenReturn(new CourseAssignmentHourAuditResult(6, 6, 0, 0, List.of()));

		TimetableExport export = service.export(TimetableExportRole.REGISTRAR, emptyQuery());

		try (Workbook workbook = read(export.content())) {
			assertNotNull(workbook.getSheet("明细"));
			assertNotNull(workbook.getSheet("课时总账"));
			assertNull(workbook.getSheet("主讲老师"), "教务总表不按教师分表");
			Sheet detail = workbook.getSheet("明细");
			Row first = detail.getRow(1);
			assertEquals("软件工程导论", first.getCell(1).getStringCellValue());
			assertEquals(2.0, first.getCell(10).getNumericCellValue(), "连续节数要如实导出");
			assertEquals(4.0, first.getCell(11).getNumericCellValue(), "结束节次 = 起始 + 连续 - 1");
		}
	}

	@Test
	void tooManySheetsIsRefusedInsteadOfProducingAnUnusableWorkbook() {
		List<CourseAssignmentView> rows = new ArrayList<>();
		for (int i = 1; i <= TimetableExportService.MAX_ENTITY_SHEETS + 1; i++) {
			rows.add(view(i, 1, 1, 3, 2, 100L + i, 1000L + i, "教师" + i, null, null,
				"11", "软工1班", 21L, "A101", "课程" + i));
		}
		when(courseAssignmentService.findViews(any())).thenReturn(rows);

		ValidationException error = assertThrows(ValidationException.class,
			() -> service.export(TimetableExportRole.TEACHER, emptyQuery()));
		assertTrue(error.getMessage().contains("收窄"), error.getMessage());
	}

	@Test
	void unknownRoleIsRejected() {
		assertThrows(ValidationException.class, () -> TimetableExportRole.from("PRINCIPAL"));
	}

	private TimetableQuery emptyQuery() {
		return TimetableQuery.of(null, null, null, null, null, null, null, null);
	}
}
