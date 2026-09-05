package com.yuy.eduflow.allocation;

import java.util.List;
import java.util.Collections;
import org.springframework.stereotype.Service;

@Service
public class AllocationTemplateService {
	private final AllocationTaskService allocationTaskService;
	private final AllocationTemplateMapper allocationTemplateMapper;
	private final AllocationTemplateDraftService allocationTemplateDraftService;

	public AllocationTemplateService(
		AllocationTaskService allocationTaskService,
		AllocationTemplateMapper allocationTemplateMapper,
		AllocationTemplateDraftService allocationTemplateDraftService
	) {
		this.allocationTaskService = allocationTaskService;
		this.allocationTemplateMapper = allocationTemplateMapper;
		this.allocationTemplateDraftService = allocationTemplateDraftService;
	}

	public List<AllocationTemplate> findTemplates(Long allocationTaskId) {
		allocationTaskService.findById(allocationTaskId);
		String generationRunId = allocationTemplateMapper.findLatestGenerationRunId(allocationTaskId);
		return generationRunId == null
			? Collections.emptyList()
			: allocationTemplateMapper.findTemplatesByRun(allocationTaskId, generationRunId);
	}

	public List<AllocationTemplateWeek> findTemplateWeeks(Long allocationTaskId) {
		allocationTaskService.findById(allocationTaskId);
		String generationRunId = allocationTemplateMapper.findLatestGenerationRunId(allocationTaskId);
		return generationRunId == null
			? Collections.emptyList()
			: allocationTemplateMapper.findTemplateWeeksByRun(allocationTaskId, generationRunId);
	}

	public AllocationTemplateWeek findTemplateWeek(Long allocationTaskId, Integer weekNumber) {
		allocationTaskService.findById(allocationTaskId);
		String generationRunId = allocationTemplateMapper.findLatestGenerationRunId(allocationTaskId);
		return generationRunId == null
			? null
			: allocationTemplateMapper.findTemplateWeekByRun(allocationTaskId, generationRunId, weekNumber);
	}

	public List<AllocationTemplateTimetableEntry> findWeekTimetable(Long allocationTaskId, Integer weekNumber) {
		allocationTaskService.findById(allocationTaskId);
		String generationRunId = allocationTemplateMapper.findLatestGenerationRunId(allocationTaskId);
		return generationRunId == null
			? Collections.emptyList()
			: allocationTemplateDraftService.findWeekTimetable(allocationTaskId, generationRunId, weekNumber);
	}
}
