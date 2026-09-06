package com.yuy.eduflow.export;

import com.yuy.eduflow.assignment.TimetableQuery;
import java.nio.charset.StandardCharsets;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 多角色课表导出入口。
 *
 * <p>返回 xlsx 字节流而不是 {@code ApiResponse} 信封，因此前端要用 blob 下载，
 * 失败时仍由全局异常处理返回 JSON。</p>
 */
@RestController
@RequestMapping("/api/exports")
public class TimetableExportController {

	private static final MediaType XLSX =
		MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

	private final TimetableExportService timetableExportService;

	public TimetableExportController(TimetableExportService timetableExportService) {
		this.timetableExportService = timetableExportService;
	}

	@GetMapping("/timetable")
	public ResponseEntity<byte[]> exportTimetable(
		@RequestParam String role,
		@RequestParam(required = false) Long teacherId,
		@RequestParam(required = false) Long classGroupId,
		@RequestParam(required = false) Long courseId,
		@RequestParam(required = false) Long classroomId,
		@RequestParam(required = false) Long allocationTaskId,
		@RequestParam(required = false) Integer weekNumber,
		@RequestParam(required = false) Integer dayOfWeek,
		@RequestParam(required = false) String status
	) {
		TimetableExport export = timetableExportService.export(
			TimetableExportRole.from(role),
			TimetableQuery.of(teacherId, classGroupId, courseId, classroomId,
				allocationTaskId, weekNumber, dayOfWeek, status)
		);
		// RFC 5987 form, so the Chinese file name survives the round trip.
		ContentDisposition disposition = ContentDisposition.attachment()
			.filename(export.fileName(), StandardCharsets.UTF_8)
			.build();
		return ResponseEntity.ok()
			.contentType(XLSX)
			.header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
			.body(export.content());
	}
}
