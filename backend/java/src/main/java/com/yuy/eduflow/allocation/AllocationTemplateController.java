package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.ApiResponse;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/allocation-tasks/{allocationTaskId}/templates")
public class AllocationTemplateController {
	private final AllocationTemplateService allocationTemplateService;
	private final AllocationTaskService allocationTaskService;
	private final V35TemplateGenerationService v35TemplateGenerationService;
	private final AllocationTaskGenerationConfigMapper generationConfigMapper;

	public AllocationTemplateController(
		AllocationTemplateService allocationTemplateService,
		AllocationTaskService allocationTaskService,
		V35TemplateGenerationService v35TemplateGenerationService,
		AllocationTaskGenerationConfigMapper generationConfigMapper
	) {
		this.allocationTemplateService = allocationTemplateService;
		this.allocationTaskService = allocationTaskService;
		this.v35TemplateGenerationService = v35TemplateGenerationService;
		this.generationConfigMapper = generationConfigMapper;
	}

	@GetMapping
	public ApiResponse<List<AllocationTemplate>> findTemplates(@PathVariable Long allocationTaskId) {
		return ApiResponse.success(allocationTemplateService.findTemplates(allocationTaskId));
	}

	@GetMapping("/weeks")
	public ApiResponse<List<AllocationTemplateWeek>> findTemplateWeeks(@PathVariable Long allocationTaskId) {
		return ApiResponse.success(allocationTemplateService.findTemplateWeeks(allocationTaskId));
	}

	@GetMapping("/weeks/{weekNumber}")
	public ApiResponse<AllocationTemplateWeek> findTemplateWeek(
		@PathVariable Long allocationTaskId,
		@PathVariable Integer weekNumber
	) {
		return ApiResponse.success(allocationTemplateService.findTemplateWeek(allocationTaskId, weekNumber));
	}

	@GetMapping("/weeks/{weekNumber}/timetable")
	public ApiResponse<List<AllocationTemplateTimetableEntry>> findWeekTimetable(
		@PathVariable Long allocationTaskId,
		@PathVariable Integer weekNumber
	) {
		return ApiResponse.success(allocationTemplateService.findWeekTimetable(allocationTaskId, weekNumber));
	}

	@PostMapping("/generate")
	public ApiResponse<V35TemplateGenerationStatus> generateTemplates(
		@PathVariable Long allocationTaskId,
		@RequestBody(required = false) Map<String, Object> params
	) {
		AllocationTaskGenerationConfig config = generationConfigMapper.findByTaskId(allocationTaskId);
		Integer totalWeeks = params != null && params.get("totalWeeks") != null
			? Integer.valueOf(params.get("totalWeeks").toString()) : maxConfiguredWeek(config);
		if (totalWeeks < SchedulingTimePolicy.FIRST_WEEK
			|| totalWeeks > SchedulingTimePolicy.LAST_WEEK) {
			throw new ValidationException("正式排课周数必须在1到18之间");
		}
		Integer topK = params != null && params.get("topK") != null
			? Integer.valueOf(params.get("topK").toString())
			: config != null && config.getPlacementTopK() != null ? config.getPlacementTopK() : 80;
		Integer maxTemplates = params != null && params.get("maxTemplates") != null
			? Integer.valueOf(params.get("maxTemplates").toString()) : 8;
		// 第一阶段只验收规则和动态模板链路，禁止从正式入口隐式训练模型。
		Boolean trainModel = false;
		Boolean importDb = params != null && Boolean.TRUE.equals(params.get("importDb"));
		Boolean truncateDb = params != null && Boolean.TRUE.equals(params.get("truncateDb"));
		allocationTaskService.validateGenerationAllowed(allocationTaskId);

		V35TemplateGenerationStatus status = v35TemplateGenerationService.startGeneration(
			allocationTaskId, totalWeeks, topK, maxTemplates, trainModel, importDb, truncateDb
		);
		return ApiResponse.success(status);
	}

	@GetMapping("/generation-status")
	public ApiResponse<V35TemplateGenerationStatus> generationStatus(@PathVariable Long allocationTaskId) {
		return ApiResponse.success(v35TemplateGenerationService.getStatus(allocationTaskId));
	}

	private int maxConfiguredWeek(AllocationTaskGenerationConfig config) {
		if (config == null || config.getAllowedWeeks() == null || config.getAllowedWeeks().isBlank()) return 18;
		int max = 0;
		for (String raw : config.getAllowedWeeks().split(",")) {
			try {
				max = Math.max(max, Integer.parseInt(raw.trim()));
			} catch (NumberFormatException ignored) {
				// AllocationTaskService 已做配置校验；旧脏值在这里忽略并回退18周。
			}
		}
		return max > 0 ? max : 18;
	}
}
