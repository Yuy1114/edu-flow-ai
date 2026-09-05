package com.yuy.eduflow.assignment;

public record CourseAssignmentMutationResult(
	CourseAssignment assignment,
	CourseAssignmentHourAuditResult hourAudit
) {
}
