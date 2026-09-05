package com.yuy.eduflow.assignment;

import java.util.List;

public record CourseAssignmentHourAuditResult(
	int requiredTotalHours,
	int scheduledTotalHours,
	int deltaTotalHours,
	int mismatchTaskCount,
	List<CourseAssignmentTaskHourAudit> tasks
) {
}
