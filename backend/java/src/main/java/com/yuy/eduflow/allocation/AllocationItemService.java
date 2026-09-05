package com.yuy.eduflow.allocation;

import com.yuy.eduflow.classroom.ClassroomService;
import com.yuy.eduflow.common.Assert;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.conflict.ConflictCheckResult;
import com.yuy.eduflow.conflict.ConflictCheckResultMapper;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import com.yuy.eduflow.teacher.TeacherProfile;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

@Slf4j
@Service
public class AllocationItemService {
	private static final String CONFLICT_BIZ_TYPE = "ALLOCATION_ITEM";

	private final AllocationItemMapper allocationItemMapper;
	private final AllocationSchemeConflictDetector conflictDetector;
	private final AllocationSchemeMapper allocationSchemeMapper;
	private final AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	private final ConflictCheckResultMapper conflictCheckResultMapper;
	private final ClassroomService classroomService;
	private final TimeSlotService timeSlotService;
	private final TeachingTaskMapper teachingTaskMapper;
	private final TeacherProfileMapper teacherProfileMapper;
	private final ObjectMapper objectMapper;
	private final MlFeedbackEventService feedbackEventService;

	public AllocationItemService(
		AllocationItemMapper allocationItemMapper,
		AllocationSchemeConflictDetector conflictDetector,
		AllocationSchemeMapper allocationSchemeMapper,
		AllocationItemAdjustmentLogMapper adjustmentLogMapper,
		ConflictCheckResultMapper conflictCheckResultMapper,
		ClassroomService classroomService,
		TimeSlotService timeSlotService,
		TeachingTaskMapper teachingTaskMapper,
		TeacherProfileMapper teacherProfileMapper,
		ObjectMapper objectMapper,
		MlFeedbackEventService feedbackEventService
	) {
		this.allocationItemMapper = allocationItemMapper;
		this.conflictDetector = conflictDetector;
		this.allocationSchemeMapper = allocationSchemeMapper;
		this.adjustmentLogMapper = adjustmentLogMapper;
		this.conflictCheckResultMapper = conflictCheckResultMapper;
		this.classroomService = classroomService;
		this.timeSlotService = timeSlotService;
		this.teachingTaskMapper = teachingTaskMapper;
		this.teacherProfileMapper = teacherProfileMapper;
		this.objectMapper = objectMapper;
		this.feedbackEventService = feedbackEventService;
	}

	public List<AllocationItemView> moveAndRecheck(Long schemeId, Long itemId, AllocationItemMoveRequest request) {
		throw legacyWriteDisabled();
	}

	private AllocationItem copyItem(AllocationItem source) {
		AllocationItem copy = new AllocationItem();
		copy.setId(source.getId());
		copy.setSchemeId(source.getSchemeId());
		copy.setTeachingTaskId(source.getTeachingTaskId());
		copy.setClassroomId(source.getClassroomId());
		copy.setTimeSlotId(source.getTimeSlotId());
		copy.setValid(source.getValid());
		copy.setConflictMessage(source.getConflictMessage());
		return copy;
	}

	private AllocationItemAdjustmentLog recordAdjustment(
		AllocationItem item,
		Long fromClassroomId,
		Long fromTimeSlotId,
		AllocationItemMoveRequest request
	) {
		boolean timeChanged = !fromTimeSlotId.equals(request.timeSlotId());
		boolean classroomChanged = !fromClassroomId.equals(request.classroomId());
		if (!timeChanged && !classroomChanged) {
			return null;
		}
		AllocationItemAdjustmentLog log = new AllocationItemAdjustmentLog();
		log.setSchemeId(item.getSchemeId());
		log.setItemId(item.getId());
		log.setTeachingTaskId(item.getTeachingTaskId());
		log.setFromTimeSlotId(fromTimeSlotId);
		log.setToTimeSlotId(request.timeSlotId());
		log.setFromClassroomId(fromClassroomId);
		log.setToClassroomId(request.classroomId());
		log.setReason(resolveAdjustmentReason(request.reason(), timeChanged, classroomChanged));
		adjustmentLogMapper.insert(log);
		return log;
	}

	private String resolveAdjustmentReason(String reason, boolean timeChanged, boolean classroomChanged) {
		if (StringUtils.hasText(reason)) {
			return reason.trim();
		}
		if (timeChanged && classroomChanged) {
			return "修改时间片+教室";
		}
		if (timeChanged) {
			return "修改时间片";
		}
		return "修改教室";
	}

	public List<AllocationItemView> recheckScheme(Long schemeId) {
		log.info("Rechecking conflicts for schemeId={}", schemeId);
		List<AllocationItem> allItems = allocationItemMapper.findAll(schemeId, null, null, null);
		AllocationScheme scheme = allocationSchemeMapper.findById(schemeId);
		Long allocationTaskId = scheme != null ? scheme.getTaskId() : null;
		List<AllocationConflictViolation> violations = conflictDetector.detect(allItems, allocationTaskId);
		log.info("Recheck done: {} violations found", violations.size());
		refreshPersistedConflictResults(schemeId, violations);
		Map<Long, String> profileMessages = buildTeacherProfileMessages(allItems);

		for (AllocationItem ai : allItems) {
			List<String> msgs = new ArrayList<>();
			for (AllocationConflictViolation v : violations) {
				if (v.itemId() != null && v.itemId().equals(ai.getId())) {
					msgs.add(v.message());
				}
			}
			if (!msgs.isEmpty()) {
				ai.setValid(false);
				ai.setConflictMessage(String.join("；", msgs));
				allocationItemMapper.updateConflictState(ai.getId(), false, ai.getConflictMessage());
			} else {
				String profileMessage = profileMessages.get(ai.getId());
				ai.setValid(true);
				ai.setConflictMessage(profileMessage);
				allocationItemMapper.updateConflictState(ai.getId(), true, profileMessage);
			}
		}

		boolean hasConflicts = !violations.isEmpty();
		String conflictSummary = hasConflicts ? conflictDetector.summarize(violations) : null;
		List<AllocationItemView> views = findViewsBySchemeId(schemeId);
		SchemeEvaluation evaluation = buildSchemeEvaluation(scheme, views, violations, profileMessages, !hasConflicts, conflictSummary);
		allocationSchemeMapper.updateEvaluationState(
			schemeId,
			evaluation.schemeScore(),
			evaluation.evaluationSummary(),
			!hasConflicts,
			conflictSummary
		);

		return views;
	}

	public AllocationScheme reevaluateScheme(Long schemeId) {
		throw legacyWriteDisabled();
	}

	private AllocationScheme findBySchemeId(Long schemeId) {
		AllocationScheme scheme = allocationSchemeMapper.findById(schemeId);
		if (scheme == null) {
			throw new ResourceNotFoundException("分课方案不存在");
		}
		return scheme;
	}

	private void refreshPersistedConflictResults(Long schemeId, List<AllocationConflictViolation> violations) {
		conflictCheckResultMapper.deleteBySchemeId(schemeId);
		for (AllocationConflictViolation violation : violations) {
			ConflictCheckResult result = new ConflictCheckResult();
			if (violation.itemId() != null) {
				result.setBizType(CONFLICT_BIZ_TYPE);
				result.setBizId(violation.itemId());
			} else {
				result.setBizType("SCHEME");
				result.setBizId(schemeId);
			}
			result.setConflictType(violation.conflictType());
			result.setMessage("方案ID " + schemeId + "：" + violation.message());
			result.setRelatedTeacherId(violation.relatedTeacherId());
			result.setRelatedClassGroupId(violation.relatedClassGroupId());
			result.setRelatedClassroomId(violation.relatedClassroomId());
			result.setRelatedTimeSlotId(violation.relatedTimeSlotId());
			result.setTeachingTaskId(violation.teachingTaskId());
			result.setCourseName(violation.courseName());
			result.setExpectedHours(violation.expectedHours());
			result.setActualHours(violation.actualHours());
			result.setResolved(false);
			conflictCheckResultMapper.insert(result);
		}
	}

	private Map<Long, String> buildTeacherProfileMessages(List<AllocationItem> items) {
		Map<Long, String> messages = new LinkedHashMap<>();
		Map<Long, TeachingTask> taskCache = new LinkedHashMap<>();
		Map<Long, TeacherProfile> profileCache = new LinkedHashMap<>();
		Map<Long, TimeSlot> slotCache = new LinkedHashMap<>();
		for (AllocationItem item : items) {
			TeachingTask task = taskCache.computeIfAbsent(item.getTeachingTaskId(), teachingTaskMapper::findById);
			if (task == null || task.getPrimaryTeacherId() == null) {
				continue;
			}
			TimeSlot slot = slotCache.computeIfAbsent(item.getTimeSlotId(), timeSlotService::findById);
			if (slot == null || slot.getDayOfWeek() == null || slot.getPeriodIndex() == null) {
				continue;
			}
			TeacherProfile profile = profileCache.computeIfAbsent(task.getPrimaryTeacherId(), teacherProfileMapper::findByTeacherId);
			String message = profilePenaltyMessage(profile, slot);
			if (StringUtils.hasText(message)) {
				messages.put(item.getId(), message);
			}
		}
		return messages;
	}

	@SuppressWarnings("unchecked")
	private String profilePenaltyMessage(TeacherProfile profile, TimeSlot slot) {
		if (profile == null || !StringUtils.hasText(profile.getProfilePreferenceJson())) {
			return null;
		}
		Map<String, Object> preference;
		try {
			preference = objectMapper.readValue(profile.getProfilePreferenceJson(), Map.class);
		} catch (Exception e) {
			log.warn("Failed to parse teacher profile preference: teacherId={}, error={}", profile.getTeacherId(), e.getMessage());
			return null;
		}
		List<String> reasons = new ArrayList<>();
		Integer day = slot.getDayOfWeek();
		Integer period = slot.getPeriodIndex();
		if (Boolean.TRUE.equals(preference.get("avoidFirstPeriod")) && period != null && period <= 2) {
			reasons.add("教师偏好避开早间第1-2节");
		}
		if (Boolean.TRUE.equals(preference.get("avoidLastPeriod")) && period != null && SchedulingTimePolicy.isEvening(period)) {
			reasons.add("教师偏好避开晚间第9-10节");
		}
		Object preferredWeekdays = preference.get("preferredWeekdays");
		if (preferredWeekdays instanceof List<?> list && !list.isEmpty() && day != null) {
			boolean matched = list.stream().anyMatch(value -> numberEquals(value, day));
			if (!matched) {
				reasons.add("未命中教师偏好星期");
			}
		}
		Object avoidSlots = preference.get("avoidSlots");
		if (avoidSlots instanceof List<?> list && day != null && period != null) {
			for (Object value : list) {
				String raw = String.valueOf(value);
				if (matchesAvoidSlotText(raw, day, period)) {
					reasons.add("命中教师软避让时间：" + raw);
				}
			}
		}
		return reasons.isEmpty() ? null : String.join("；", reasons);
	}

	private boolean numberEquals(Object value, int expected) {
		if (value instanceof Number number) {
			return number.intValue() == expected;
		}
		try {
			return Integer.parseInt(String.valueOf(value)) == expected;
		} catch (NumberFormatException ignored) {
			return false;
		}
	}

	private boolean matchesAvoidSlotText(String raw, int day, int period) {
		if (!StringUtils.hasText(raw)) {
			return false;
		}
		String[] dayNames = {"", "周一", "周二", "周三", "周四", "周五", "周六", "周日"};
		boolean dayMatched = raw.contains(dayNames[day]) || raw.contains("星期" + "一二三四五六日".charAt(day - 1));
		boolean periodMatched = raw.contains("第" + period + "节") || raw.contains(period + "节");
		return dayMatched && (periodMatched || !raw.matches(".*\\d+节.*"));
	}

	private SchemeEvaluation buildSchemeEvaluation(
		AllocationScheme scheme,
		List<AllocationItemView> views,
		List<AllocationConflictViolation> violations,
		Map<Long, String> profileMessages,
		boolean valid,
		String conflictSummary
	) {
		// Diagnostic info only — authoritative scoring is from ML pipeline
		double profilePenaltyTotal = profileMessages.values().stream()
			.mapToDouble(this::profilePenaltyValue)
			.sum();
		int profilePenaltyHitCount = profileMessages.size();
		double teacherScore = clampScore(100.0 - profilePenaltyTotal);
		double classBalanceScore = calculateClassBalanceScore(views);
		Double schemeScore = scheme != null ? scheme.getSchemeScore() : null;

		Map<String, Object> summary = parseEvaluationSummary(scheme != null ? scheme.getEvaluationSummary() : null);
		Object previousSolverSummary = summary.getOrDefault("solver_summary", summary.get("ga_summary"));
		summary.clear();
		summary.put("scheme_score", schemeScore);
		summary.put("teacher_score_diagnostic", Math.round(teacherScore));
		summary.put("class_balance_score_diagnostic", Math.round(classBalanceScore));
		summary.put("teacher_profile_penalty_hit_count", profilePenaltyHitCount);
		summary.put("teacher_profile_penalty_total", round1(profilePenaltyTotal));
		summary.put("hard_conflict_count", violations.size());
		summary.put("valid", valid);
		summary.put("conflict_summary", conflictSummary);
		summary.put("teacher_profile_audit", buildManualTeacherProfileAudit(profileMessages));
		if (previousSolverSummary != null) {
			summary.put("solver_summary", previousSolverSummary);
		}

		Map<String, Object> reevaluation = new LinkedHashMap<>();
		reevaluation.put("source", "java_manual_adjustment_v1");
		reevaluation.put("evaluated_at", LocalDateTime.now().toString());
		reevaluation.put("model_score_stale", true);
		reevaluation.put("note", "手动调整后 retains ML quality_score; Java recalc stashed as diagnostic");
		summary.put("reevaluation", reevaluation);

		return new SchemeEvaluation(schemeScore, toJson(summary));
	}

	private Map<String, Object> buildManualTeacherProfileAudit(Map<Long, String> profileMessages) {
		Map<String, Object> audit = new LinkedHashMap<>();
		audit.put("source", "manual_reevaluation");
		audit.put("candidate_slot_removed_by_hard_filter", 0);
		audit.put("hard_unavailable_task_count", 0);
		audit.put("profile_penalty_hit_count", profileMessages.size());
		audit.put("tasks", List.of());
		return audit;
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> parseEvaluationSummary(String rawJson) {
		if (!StringUtils.hasText(rawJson)) {
			return new LinkedHashMap<>();
		}
		try {
			return new LinkedHashMap<>(objectMapper.readValue(rawJson, Map.class));
		} catch (Exception e) {
			log.warn("Failed to parse existing evaluation summary: {}", e.getMessage());
			return new LinkedHashMap<>();
		}
	}

	private String toJson(Map<String, Object> value) {
		try {
			return objectMapper.writeValueAsString(value);
		} catch (Exception e) {
			log.warn("Failed to serialize reevaluation summary: {}", e.getMessage());
			return "{}";
		}
	}

	private double profilePenaltyValue(String message) {
		if (!StringUtils.hasText(message)) {
			return 0.0;
		}
		return Math.max(1, message.split("；").length) * 10.0;
	}

	private double calculateClassBalanceScore(List<AllocationItemView> views) {
		Map<String, Map<Integer, Integer>> byClassGroup = new LinkedHashMap<>();
		for (AllocationItemView view : views) {
			if (view.getDayOfWeek() == null || !StringUtils.hasText(view.getClassGroupName())) {
				continue;
			}
			for (String rawGroup : view.getClassGroupName().split(",")) {
				String classGroup = rawGroup.trim();
				if (!StringUtils.hasText(classGroup)) {
					continue;
				}
				byClassGroup
					.computeIfAbsent(classGroup, ignored -> new LinkedHashMap<>())
					.merge(view.getDayOfWeek(), 1, Integer::sum);
			}
		}
		if (byClassGroup.isEmpty()) {
			return 100.0;
		}
		double totalScore = 0.0;
		for (Map<Integer, Integer> dayCounts : byClassGroup.values()) {
			int total = dayCounts.values().stream().mapToInt(Integer::intValue).sum();
			if (total <= 1) {
				totalScore += 100.0;
				continue;
			}
			Set<Integer> days = new HashSet<>(List.of(1, 2, 3, 4, 5));
			days.addAll(dayCounts.keySet());
			double ideal = (double) total / days.size();
			double deviation = days.stream()
				.mapToDouble(day -> Math.abs(dayCounts.getOrDefault(day, 0) - ideal))
				.sum() / days.size();
			totalScore += clampScore(100.0 - deviation * 18.0);
		}
		return totalScore / byClassGroup.size();
	}

	private double clampScore(double value) {
		return Math.max(0.0, Math.min(100.0, value));
	}

	private double round1(double value) {
		return Math.round(value * 10.0) / 10.0;
	}

	private record SchemeEvaluation(Double schemeScore, String evaluationSummary) {
	}

	public List<AllocationItem> findAll(
		Long schemeId,
		Long teachingTaskId,
		Long classroomId,
		Long timeSlotId
	) {
		validateOptionalId(schemeId, "分课方案ID必须大于0");
		validateOptionalId(teachingTaskId, "教学任务ID必须大于0");
		validateOptionalId(classroomId, "教室ID必须大于0");
		validateOptionalId(timeSlotId, "时间段ID必须大于0");
		return allocationItemMapper.findAll(schemeId, teachingTaskId, classroomId, timeSlotId);
	}

	public List<AllocationItemView> findViewsBySchemeId(Long schemeId) {
		validateOptionalId(schemeId, "分课方案ID必须大于0");
		return allocationItemMapper.findViewsBySchemeId(schemeId);
	}

	public AllocationItem findById(Long id) {
		AllocationItem item = allocationItemMapper.findById(id);
		if (item == null) {
			throw new ResourceNotFoundException("分课明细不存在");
		}
		return item;
	}

	public AllocationItem create(AllocationItemRequest request) {
		throw legacyWriteDisabled();
	}

	public AllocationItem update(Long id, AllocationItemRequest request) {
		throw legacyWriteDisabled();
	}

	public void delete(Long id) {
		throw legacyWriteDisabled();
	}

	private ValidationException legacyWriteDisabled() {
		return new ValidationException("第一阶段旧版allocation_item链路只读；请使用V3.5模板草案片段接口编辑和重审计");
	}

	private AllocationItem toItem(AllocationItem item, AllocationItemRequest request) {
		Assert.positiveId(request.schemeId(), "分课方案ID");
		Assert.positiveId(request.teachingTaskId(), "教学任务ID");
		Assert.positiveId(request.classroomId(), "教室ID");
		Assert.positiveId(request.timeSlotId(), "时间段ID");
		validateTeachingSessionBlock(request.teachingTaskId(), request.timeSlotId());
		item.setSchemeId(request.schemeId());
		item.setTeachingTaskId(request.teachingTaskId());
		item.setClassroomId(request.classroomId());
		item.setTimeSlotId(request.timeSlotId());
		item.setValid(request.valid() != null ? request.valid() : true);
		item.setConflictMessage(clean(request.conflictMessage()));
		return item;
	}

	private void validateTeachingSessionBlock(Long teachingTaskId, Long timeSlotId) {
		TeachingTask task = teachingTaskMapper.findWithDetails(teachingTaskId);
		if (task == null) {
			throw new ResourceNotFoundException("教学任务不存在");
		}
		TimeSlot slot = timeSlotService.findById(timeSlotId);
		String courseType = task.getCourse() == null ? null : task.getCourse().getCourseType();
		int periodCount = TeachingSessionTimePolicy.periodCount(courseType);
		if (periodCount == 0) {
			throw new ValidationException("教学任务课程类型缺失或不支持，无法确定一次课占用2节还是4节");
		}
		if (!TeachingSessionTimePolicy.isLegalStartPeriod(slot.getPeriodIndex(), periodCount)) {
			throw new ValidationException(
				courseType + "一次课占连续" + periodCount + "节，起始节次只能是"
					+ TeachingSessionTimePolicy.legalStartDescription(periodCount)
					+ "，不能跨上午、下午或晚间边界"
			);
		}
	}

	private void validateOptionalId(Long id, String message) {
		if (id != null && id <= 0) {
			throw new ValidationException(message);
		}
	}

	private String clean(String value) {
		return StringUtils.hasText(value) ? value.trim() : null;
	}
}
