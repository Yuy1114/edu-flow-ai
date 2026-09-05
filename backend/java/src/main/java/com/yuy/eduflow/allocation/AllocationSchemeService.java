package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.Assert;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.conflict.ConflictCheckResult;
import com.yuy.eduflow.conflict.ConflictCheckResultMapper;
import com.yuy.eduflow.conflict.ConflictDiagnosis;
import com.yuy.eduflow.enums.SchemeStatus;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class AllocationSchemeService {

	private final AllocationSchemeMapper allocationSchemeMapper;
	private final ConflictCheckResultMapper conflictCheckResultMapper;
	private final AllocationTemplateDraftService allocationTemplateDraftService;

	public AllocationSchemeService(
		AllocationSchemeMapper allocationSchemeMapper,
		ConflictCheckResultMapper conflictCheckResultMapper,
		AllocationTemplateDraftService allocationTemplateDraftService
	) {
		this.allocationSchemeMapper = allocationSchemeMapper;
		this.conflictCheckResultMapper = conflictCheckResultMapper;
		this.allocationTemplateDraftService = allocationTemplateDraftService;
	}

	public List<AllocationScheme> findAll(Long taskId, String status) {
		if (taskId != null && taskId <= 0) {
			throw new ValidationException("分课任务ID必须大于0");
		}
		return allocationSchemeMapper.findAll(taskId, status);
	}

	public AllocationScheme findById(Long id) {
		AllocationScheme scheme = allocationSchemeMapper.findById(id);
		if (scheme == null) {
			throw new ResourceNotFoundException("分课方案不存在");
		}
		return scheme;
	}

	public AllocationScheme create(AllocationSchemeRequest request) {
		throw new ValidationException("第一阶段已统一使用V3.5动态模板生成方案，禁止通过旧版接口人工创建方案");
	}

	@Transactional
	public AllocationScheme update(Long id, AllocationSchemeRequest request) {
		AllocationScheme existing = allocationSchemeMapper.findByIdForUpdate(id);
		if (existing == null) throw new ResourceNotFoundException("分课方案不存在");
		if (existing.getStatus() == SchemeStatus.CONFIRMED) {
			throw new ValidationException("已确认方案不可修改");
		}
		if (allocationTemplateDraftService.isV35(existing)) {
			throw new ValidationException("V3.5方案只能通过模板草案专用接口编辑，生成批次和审计状态不可覆盖");
		}
		if (existing.getStatus() != SchemeStatus.CANDIDATE) {
			throw new ValidationException("只有候选方案可以修改名称");
		}
		if (request == null || !StringUtils.hasText(request.schemeName())) {
			throw new ValidationException("分课方案名称不能为空");
		}
		if (allocationSchemeMapper.updateCandidateName(id, request.schemeName().trim()) != 1) {
			throw new ValidationException("方案状态已变化，修改未保存");
		}
		return findById(id);
	}

	@Transactional
	public void delete(Long id) {
		AllocationScheme scheme = allocationSchemeMapper.findByIdForUpdate(id);
		if (scheme == null) throw new ResourceNotFoundException("分课方案不存在");
		if (scheme.getStatus() == SchemeStatus.CONFIRMED) {
			throw new ValidationException("已确认方案不可删除或改写生命周期状态");
		}
		if (allocationTemplateDraftService.isV35(scheme)) {
			throw new ValidationException("V3.5方案与整批动态模板共享生成结果；请删除排课任务或重新生成，不能单独删除方案元数据");
		}
		if (scheme.getStatus() != SchemeStatus.CANDIDATE) {
			throw new ValidationException("只有候选方案可以拒绝删除");
		}
		if (allocationSchemeMapper.updateStatusIfCurrent(
			id, SchemeStatus.CANDIDATE.code(), SchemeStatus.REJECTED.code()
		) != 1) {
			throw new ValidationException("方案状态已变化，删除未执行");
		}
	}

	public ConflictDiagnosis findConflictDiagnosis(Long schemeId) {
		findById(schemeId);
		List<ConflictCheckResult> raw = conflictCheckResultMapper.findBySchemeId(schemeId);
		if (raw == null || raw.isEmpty()) {
			return new ConflictDiagnosis("该方案无明显冲突", 0, true, Map.of(), List.of());
		}

		Map<String, List<ConflictDiagnosis.ConflictDiagnosisItem>> groups = new LinkedHashMap<>();
		List<ConflictDiagnosis.ConflictDiagnosisItem> hoursMismatch = new ArrayList<>();

		String[] order = {"TEACHER_TIME", "CLASS_GROUP_TIME", "CLASSROOM_TIME", "TEACHER_WORKLOAD"};
		for (String type : order) {
			groups.put(type, new ArrayList<>());
		}

		for (ConflictCheckResult r : raw) {
			ConflictDiagnosis.ConflictDiagnosisItem item = new ConflictDiagnosis.ConflictDiagnosisItem(
				r.getId(),
				r.getBizType(),
				r.getBizId(),
				r.getConflictType(),
				typeLabel(r.getConflictType()),
				r.getMessage(),
				r.getRelatedTeacherId(),
				r.getRelatedTeacherName(),
				r.getRelatedClassGroupId(),
				r.getRelatedClassGroupName(),
				r.getRelatedClassroomId(),
				r.getRelatedClassroomName(),
				r.getRelatedTimeSlotId(),
				r.getRelatedTimeSlotLabel(),
				r.getTeachingTaskId(),
				r.getCourseName(),
				r.getExpectedHours(),
				r.getActualHours()
			);
			if ("TEACHING_TASK_HOURS".equals(r.getConflictType())) {
				hoursMismatch.add(item);
			} else {
				groups.computeIfAbsent(r.getConflictType(), k -> new ArrayList<>()).add(item);
			}
		}

		// Remove empty groups
		groups.entrySet().removeIf(e -> e.getValue().isEmpty());

		int total = raw.size();
		boolean clean = total == 0;
		String summary = buildSummary(total, groups, hoursMismatch);
		return new ConflictDiagnosis(summary, total, clean, groups, hoursMismatch);
	}

	private String typeLabel(String type) {
		return switch (type) {
			case "TEACHER_TIME" -> "教师时间冲突";
			case "CLASS_GROUP_TIME" -> "班级时间冲突";
			case "CLASSROOM_TIME" -> "教室时间冲突";
			case "INVALID_TIME_BLOCK" -> "非法连排时间块";
			case "TEACHER_WORKLOAD" -> "教师工作量冲突";
			case "TEACHING_TASK_HOURS" -> "教学任务课时不匹配";
			default -> "未知冲突";
		};
	}

	private String buildSummary(int total, Map<String, List<ConflictDiagnosis.ConflictDiagnosisItem>> groups, List<ConflictDiagnosis.ConflictDiagnosisItem> hoursMismatch) {
		if (total == 0) return "该方案无明显冲突";
		List<String> parts = new ArrayList<>();
		for (Map.Entry<String, List<ConflictDiagnosis.ConflictDiagnosisItem>> e : groups.entrySet()) {
			parts.add(typeLabel(e.getKey()) + " " + e.getValue().size() + " 条");
		}
		if (!hoursMismatch.isEmpty()) {
			parts.add("教学任务课时不匹配 " + hoursMismatch.size() + " 条");
		}
		return "共发现 " + total + " 条问题：" + String.join("，", parts);
	}

}
