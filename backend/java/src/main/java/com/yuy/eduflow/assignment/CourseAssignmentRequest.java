package com.yuy.eduflow.assignment;

public record CourseAssignmentRequest(
	Long sourceSchemeId,
	Long teachingTaskId,
	Long classroomId,
	Long timeSlotId,
	Integer consecutiveSlots,
	String status
) {
}
