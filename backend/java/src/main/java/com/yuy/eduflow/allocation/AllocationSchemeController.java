package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.ApiResponse;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.conflict.ConflictDiagnosis;
import com.yuy.eduflow.ml.MlFeedbackEvent;
import com.yuy.eduflow.ml.MlFeedbackEventMarkRequest;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import java.util.List;
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
@RequestMapping("/api/allocation-schemes")
public class AllocationSchemeController {
	private final AllocationSchemeService allocationSchemeService;
	private final AllocationItemService allocationItemService;
	private final AllocationSchemeConfirmService allocationSchemeConfirmService;
	private final AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	private final MlFeedbackEventService feedbackEventService;
	private final AllocationTemplateDraftService allocationTemplateDraftService;

	public AllocationSchemeController(
		AllocationSchemeService allocationSchemeService,
		AllocationItemService allocationItemService,
		AllocationSchemeConfirmService allocationSchemeConfirmService,
		AllocationItemAdjustmentLogMapper adjustmentLogMapper,
		MlFeedbackEventService feedbackEventService,
		AllocationTemplateDraftService allocationTemplateDraftService
	) {
		this.allocationSchemeService = allocationSchemeService;
		this.allocationItemService = allocationItemService;
		this.allocationSchemeConfirmService = allocationSchemeConfirmService;
		this.adjustmentLogMapper = adjustmentLogMapper;
		this.feedbackEventService = feedbackEventService;
		this.allocationTemplateDraftService = allocationTemplateDraftService;
	}

	@GetMapping
	public ApiResponse<List<AllocationScheme>> findAll(
		@RequestParam(required = false) Long taskId,
		@RequestParam(required = false) String status
	) {
		return ApiResponse.success(allocationSchemeService.findAll(taskId, status));
	}

	@GetMapping("/{id}")
	public ApiResponse<AllocationScheme> findById(@PathVariable Long id) {
		return ApiResponse.success(allocationSchemeService.findById(id));
	}

	@GetMapping("/{id}/items")
	public ApiResponse<List<AllocationItemView>> findItems(@PathVariable Long id) {
		AllocationScheme scheme = allocationSchemeService.findById(id);
		String modelVersion = scheme.getModelVersion();
		if (modelVersion != null && modelVersion.startsWith("v3.5")) {
			return ApiResponse.success(allocationTemplateDraftService.findSchemeItems(id));
		}
		return ApiResponse.success(allocationItemService.findViewsBySchemeId(id));
	}

	@GetMapping("/{id}/conflicts")
	public ApiResponse<ConflictDiagnosis> findConflicts(@PathVariable Long id) {
		allocationSchemeService.findById(id);
		return ApiResponse.success(allocationSchemeService.findConflictDiagnosis(id));
	}

	@PostMapping
	public ApiResponse<AllocationScheme> create(@RequestBody AllocationSchemeRequest request) {
		return ApiResponse.success(allocationSchemeService.create(request));
	}

	@PostMapping("/{id}/confirm")
	public ApiResponse<AllocationConfirmResult> confirm(@PathVariable Long id) {
		return ApiResponse.success(allocationSchemeConfirmService.confirm(id));
	}

	@PostMapping("/{id}/reevaluate")
	public ApiResponse<AllocationScheme> reevaluate(@PathVariable Long id) {
		AllocationScheme scheme = allocationSchemeService.findById(id);
		if (allocationTemplateDraftService.isV35(scheme)) {
			allocationTemplateDraftService.auditAndPersist(id);
			return ApiResponse.success(allocationSchemeService.findById(id));
		}
		return ApiResponse.success(allocationItemService.reevaluateScheme(id));
	}

	@GetMapping("/{id}/template-draft")
	public ApiResponse<AllocationTemplateDraftView> findTemplateDraft(@PathVariable Long id) {
		return ApiResponse.success(allocationTemplateDraftService.findDraft(id));
	}

	@PostMapping("/{id}/template-fragments")
	public ApiResponse<AllocationTemplateDraftView> createTemplateFragment(
		@PathVariable Long id,
		@RequestBody AllocationTemplateFragmentRequest request
	) {
		return ApiResponse.success(allocationTemplateDraftService.createFragment(id, request));
	}

	@PutMapping("/{id}/template-fragments/{fragmentId}")
	public ApiResponse<AllocationTemplateDraftView> updateTemplateFragment(
		@PathVariable Long id,
		@PathVariable Long fragmentId,
		@RequestBody AllocationTemplateFragmentRequest request
	) {
		return ApiResponse.success(allocationTemplateDraftService.updateFragment(id, fragmentId, request));
	}

	@DeleteMapping("/{id}/template-fragments/{fragmentId}")
	public ApiResponse<AllocationTemplateDraftView> deleteTemplateFragment(
		@PathVariable Long id,
		@PathVariable Long fragmentId,
		@RequestParam(required = false) String reason
	) {
		return ApiResponse.success(allocationTemplateDraftService.deleteFragment(id, fragmentId, reason));
	}

	@PostMapping("/{id}/manual-review-acceptance")
	public ApiResponse<AllocationTemplateDraftView> acceptTemplateManualReview(
		@PathVariable Long id,
		@RequestBody AllocationTemplateManualReviewRequest request
	) {
		return ApiResponse.success(allocationTemplateDraftService.acceptManualReview(id, request));
	}

	@PutMapping("/{id}")
	public ApiResponse<AllocationScheme> update(@PathVariable Long id, @RequestBody AllocationSchemeRequest request) {
		return ApiResponse.success(allocationSchemeService.update(id, request));
	}

	@DeleteMapping("/{id}")
	public ApiResponse<Void> delete(@PathVariable Long id) {
		allocationSchemeService.delete(id);
		return ApiResponse.success();
	}

	@PostMapping("/{schemeId}/adjustment-log")
	public ApiResponse<Void> recordAdjustment(
		@PathVariable Long schemeId,
		@RequestBody AdjustmentLogRequest request
	) {
		AllocationItemAdjustmentLog log = new AllocationItemAdjustmentLog();
		log.setSchemeId(schemeId);
		log.setItemId(request.itemId());
		log.setTeachingTaskId(request.teachingTaskId());
		log.setFromTimeSlotId(request.fromTimeSlotId());
		log.setToTimeSlotId(request.toTimeSlotId());
		log.setFromClassroomId(request.fromClassroomId());
		log.setToClassroomId(request.toClassroomId());
		log.setReason(request.reason());
		adjustmentLogMapper.insert(log);
		return ApiResponse.success();
	}

	@PutMapping("/{schemeId}/items/{itemId}")
	public ApiResponse<List<AllocationItemView>> moveItem(
		@PathVariable Long schemeId,
		@PathVariable Long itemId,
		@RequestBody AllocationItemMoveRequest request
	) {
		AllocationScheme scheme = allocationSchemeService.findById(schemeId);
		if (allocationTemplateDraftService.isV35(scheme)) {
			allocationTemplateDraftService.moveFragmentFromLegacyRequest(schemeId, itemId, request);
			return ApiResponse.success(allocationTemplateDraftService.findSchemeItems(schemeId));
		}
		return ApiResponse.success(allocationItemService.moveAndRecheck(schemeId, itemId, request));
	}

	@PostMapping("/{schemeId}/items/{itemId}/feedback")
	public ApiResponse<MlFeedbackEvent> markItem(
		@PathVariable Long schemeId,
		@PathVariable Long itemId,
		@RequestBody MlFeedbackEventMarkRequest request
	) {
		AllocationScheme scheme = allocationSchemeService.findById(schemeId);
		if (allocationTemplateDraftService.isV35(scheme)) {
			throw new ValidationException("V3.5模板片段请通过草案编辑接口记录调整反馈");
		}
		return ApiResponse.success(feedbackEventService.markItem(schemeId, itemId, request));
	}
}
