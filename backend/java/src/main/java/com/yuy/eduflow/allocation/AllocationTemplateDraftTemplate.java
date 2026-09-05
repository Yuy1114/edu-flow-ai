package com.yuy.eduflow.allocation;

import java.util.List;

public record AllocationTemplateDraftTemplate(
	Long id,
	String templateCode,
	String templateName,
	int fragmentCount,
	int taskCount,
	List<Integer> weekNumbers
) {
}
