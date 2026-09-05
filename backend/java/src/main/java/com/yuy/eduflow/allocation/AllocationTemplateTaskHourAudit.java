package com.yuy.eduflow.allocation;

public record AllocationTemplateTaskHourAudit(
	Long teachingTaskId,
	String courseName,
	int requiredHours,
	int scheduledHours,
	int deltaHours,
	int sessionPeriods,
	String status
) {
}
