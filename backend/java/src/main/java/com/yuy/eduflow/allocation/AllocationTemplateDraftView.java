package com.yuy.eduflow.allocation;

import java.util.List;

public record AllocationTemplateDraftView(
	Long schemeId,
	Long allocationTaskId,
	String generationRunId,
	List<AllocationTemplateDraftTemplate> templates,
	AllocationTemplateAuditResult audit,
	AllocationTeacherSatisfactionView satisfaction
) {
}
