package com.yuy.eduflow.allocation;

import java.util.List;

public record AllocationTemplateAuditResult(
	String reviewStatus,
	boolean valid,
	int hardConflictCount,
	int teacherConflictCount,
	int classGroupConflictCount,
	int classroomConflictCount,
	int capacityMismatchCount,
	int roomTypeMismatchCount,
	int identityIssueCount,
	int hourMismatchTaskCount,
	int requiredTotalHours,
	int scheduledTotalHours,
	int deltaTotalHours,
	List<AllocationTemplateTaskHourAudit> taskHours,
	List<String> issues
) {
}
