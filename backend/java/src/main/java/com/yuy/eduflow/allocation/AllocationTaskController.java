package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.ApiResponse;
import com.yuy.eduflow.ml.MlApiClient;
import java.util.List;
import java.util.Map;
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
@RequestMapping("/api/allocation-tasks")
public class AllocationTaskController {
	private final AllocationTaskService allocationTaskService;
	private final AllocationSchemeService allocationSchemeService;
	private final MlApiClient mlApiClient;

	public AllocationTaskController(
		AllocationTaskService allocationTaskService,
		AllocationSchemeService allocationSchemeService,
		MlApiClient mlApiClient
	) {
		this.allocationTaskService = allocationTaskService;
		this.allocationSchemeService = allocationSchemeService;
		this.mlApiClient = mlApiClient;
	}

	@GetMapping
	public ApiResponse<List<AllocationTask>> findAll(
		@RequestParam(required = false) String keyword,
		@RequestParam(required = false) String status
	) {
		return ApiResponse.success(allocationTaskService.findAll(keyword, status));
	}

	@GetMapping("/{id}")
	public ApiResponse<AllocationTask> findById(@PathVariable Long id) {
		return ApiResponse.success(allocationTaskService.findById(id));
	}

	@GetMapping("/{id}/schemes")
	public ApiResponse<List<AllocationScheme>> findSchemes(@PathVariable Long id) {
		allocationTaskService.findById(id);
		return ApiResponse.success(allocationSchemeService.findAll(id, null));
	}

	@PostMapping
	public ApiResponse<AllocationTask> create(@RequestBody AllocationTaskRequest request) {
		return ApiResponse.success(allocationTaskService.create(request));
	}

	@PutMapping("/{id}")
	public ApiResponse<AllocationTask> update(@PathVariable Long id, @RequestBody AllocationTaskRequest request) {
		return ApiResponse.success(allocationTaskService.update(id, request));
	}

	@DeleteMapping("/{id}")
	public ApiResponse<Void> delete(@PathVariable Long id) {
		allocationTaskService.delete(id);
		return ApiResponse.success();
	}

	// ── LLM Constraint Endpoints ─────────────────────────────────────

	@PostMapping("/{id}/translate-constraint")
	public ApiResponse<Map<String, Object>> translateConstraint(
		@PathVariable Long id,
		@RequestBody Map<String, String> body
	) {
		String text = body.get("text");
		if (text == null || text.isBlank()) {
			@SuppressWarnings("unchecked")
			var err = (ApiResponse<Map<String, Object>>) (ApiResponse<?>) ApiResponse.error(400, "text is required");
			return err;
		}
		Map<String, Object> result = mlApiClient.translateConstraint(text);
		return ApiResponse.success(result);
	}

	@PutMapping("/{id}/constraints/toggle")
	public ApiResponse<Void> toggleConstraint(
		@PathVariable Long id,
		@RequestBody Map<String, String> body
	) {
		String constraintId = body.get("constraintId");
		AllocationTaskGenerationConfig config = allocationTaskService.getGenerationConfig(id);
		if (config == null) {
			return ApiResponse.error(404, "config not found for task " + id);
		}
		String overridesJson = config.getLlmOverrides();
		if (overridesJson == null || overridesJson.isBlank()) {
			return ApiResponse.error(404, "no llm overrides found");
		}
		allocationTaskService.toggleConstraint(id, constraintId);
		return ApiResponse.success();
	}

	@DeleteMapping("/{id}/constraints/{constraintId}")
	public ApiResponse<Void> deleteConstraint(
		@PathVariable Long id,
		@PathVariable String constraintId
	) {
		allocationTaskService.deleteConstraint(id, constraintId);
		return ApiResponse.success();
	}

	@GetMapping("/{id}/config")
	public ApiResponse<AllocationTaskGenerationConfig> getConfig(@PathVariable Long id) {
		return ApiResponse.success(allocationTaskService.getGenerationConfig(id));
	}

	@PutMapping("/{id}/config")
	public ApiResponse<AllocationTaskGenerationConfig> updateConfig(
		@PathVariable Long id,
		@RequestBody AllocationTaskGenerationConfigRequest request
	) {
		return ApiResponse.success(allocationTaskService.updateGenerationConfig(id, request));
	}
}
