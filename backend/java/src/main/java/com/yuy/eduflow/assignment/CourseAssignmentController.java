package com.yuy.eduflow.assignment;

import com.yuy.eduflow.common.ApiResponse;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/course-assignments")
public class CourseAssignmentController {
	private final CourseAssignmentService courseAssignmentService;

	public CourseAssignmentController(CourseAssignmentService courseAssignmentService) {
		this.courseAssignmentService = courseAssignmentService;
	}

	@GetMapping
	public ApiResponse<List<CourseAssignmentView>> findAll(
		@RequestParam(required = false) Long teacherId,
		@RequestParam(required = false) Long classGroupId,
		@RequestParam(required = false) Long courseId,
		@RequestParam(required = false) Long classroomId,
		@RequestParam(required = false) Long allocationTaskId,
		@RequestParam(required = false) Integer weekNumber,
		@RequestParam(required = false) Integer dayOfWeek,
		@RequestParam(required = false) String status
	) {
		return ApiResponse.success(courseAssignmentService.findViews(TimetableQuery.of(
			teacherId,
			classGroupId,
			courseId,
			classroomId,
			allocationTaskId,
			weekNumber,
			dayOfWeek,
			status
		)));
	}

	@GetMapping("/{id}")
	public ApiResponse<CourseAssignment> findById(@PathVariable Long id) {
		return ApiResponse.success(courseAssignmentService.findById(id));
	}

	@GetMapping("/hour-audit")
	public ApiResponse<CourseAssignmentHourAuditResult> findHourAudit(
		@RequestParam(required = false) Long allocationTaskId,
		@RequestParam(required = false) Long teachingTaskId
	) {
		return ApiResponse.success(courseAssignmentService.findHourAudit(allocationTaskId, teachingTaskId));
	}

	@PostMapping
	public ApiResponse<CourseAssignmentMutationResult> create(@RequestBody CourseAssignmentRequest request) {
		return ApiResponse.success(courseAssignmentService.create(request));
	}

	@PutMapping("/{id}")
	public ApiResponse<CourseAssignmentMutationResult> update(@PathVariable Long id, @RequestBody CourseAssignmentRequest request) {
		return ApiResponse.success(courseAssignmentService.update(id, request));
	}

	@PutMapping("/{id}/move")
	public ApiResponse<CourseAssignmentMutationResult> move(
		@PathVariable Long id,
		@RequestParam Long timeSlotId,
		@RequestParam(required = false) Long classroomId
	) {
		return ApiResponse.success(courseAssignmentService.moveAndRecheck(id, timeSlotId, classroomId));
	}

	@DeleteMapping("/{id}")
	public ApiResponse<CourseAssignmentMutationResult> delete(@PathVariable Long id) {
		return ApiResponse.success(courseAssignmentService.delete(id));
	}
}
