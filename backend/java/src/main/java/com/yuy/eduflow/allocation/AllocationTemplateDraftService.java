package com.yuy.eduflow.allocation;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.common.Assert;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.SchemeStatus;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

/**
 * V3.5 模板草案的人工编辑、审计和正式发布准备服务。
 *
 * <p>本服务只操作 {@code schedule_template_*}；旧版
 * {@code allocation_item} 从不作为 V3.5 草案的写入目标。</p>
 */
@Slf4j
@Service
public class AllocationTemplateDraftService {
	private final AllocationSchemeMapper schemeMapper;
	private final AllocationTemplateMapper templateMapper;
	private final TeachingTaskMapper teachingTaskMapper;
	private final ClassroomMapper classroomMapper;
	private final TimeSlotService timeSlotService;
	private final AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	private final AllocationSchemeFeedbackMapper schemeFeedbackMapper;
	private final MlFeedbackEventService feedbackEventService;
	private final ObjectMapper objectMapper;

	public AllocationTemplateDraftService(
		AllocationSchemeMapper schemeMapper,
		AllocationTemplateMapper templateMapper,
		TeachingTaskMapper teachingTaskMapper,
		ClassroomMapper classroomMapper,
		TimeSlotService timeSlotService,
		AllocationItemAdjustmentLogMapper adjustmentLogMapper,
		AllocationSchemeFeedbackMapper schemeFeedbackMapper,
		MlFeedbackEventService feedbackEventService,
		ObjectMapper objectMapper
	) {
		this.schemeMapper = schemeMapper;
		this.templateMapper = templateMapper;
		this.teachingTaskMapper = teachingTaskMapper;
		this.classroomMapper = classroomMapper;
		this.timeSlotService = timeSlotService;
		this.adjustmentLogMapper = adjustmentLogMapper;
		this.schemeFeedbackMapper = schemeFeedbackMapper;
		this.feedbackEventService = feedbackEventService;
		this.objectMapper = objectMapper;
	}

	public boolean isV35(AllocationScheme scheme) {
		return scheme != null
			&& StringUtils.hasText(scheme.getModelVersion())
			&& scheme.getModelVersion().startsWith("v3.5");
	}

	public AllocationTemplateDraftView findDraft(Long schemeId) {
		AllocationScheme scheme = requireV35Scheme(schemeId, false);
		String runId = generationRunId(scheme);
		AllocationTemplateDraftAuditor.Snapshot snapshot = auditSnapshot(scheme, runId, false);
		return draftView(scheme, runId, snapshot);
	}

	private AllocationTemplateDraftView draftView(
		AllocationScheme scheme,
		String runId,
		AllocationTemplateDraftAuditor.Snapshot snapshot
	) {
		return new AllocationTemplateDraftView(
			scheme.getId(),
			scheme.getTaskId(),
			runId,
			findDraftTemplates(scheme.getTaskId(), runId),
			snapshot.result()
		);
	}

	@Transactional
	public AllocationTemplateAuditResult auditAndPersist(Long schemeId) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		return auditSnapshot(scheme, generationRunId(scheme), true).result();
	}

	public List<AllocationItemView> findSchemeItems(Long schemeId) {
		AllocationScheme scheme = requireV35Scheme(schemeId, false);
		String runId = generationRunId(scheme);
		List<AllocationTemplateAuditEntry> entries = templateMapper.findAuditEntriesByRun(scheme.getTaskId(), runId);
		Map<Long, List<Integer>> weeksByFragment = entries.stream()
			.filter(entry -> entry.getTemplateFragmentId() != null && entry.getWeekNumber() != null)
			.collect(Collectors.groupingBy(
				AllocationTemplateAuditEntry::getTemplateFragmentId,
				LinkedHashMap::new,
				Collectors.collectingAndThen(
					Collectors.mapping(AllocationTemplateAuditEntry::getWeekNumber, Collectors.toCollection(java.util.TreeSet::new)),
					List::copyOf
				)
			));
		AllocationTemplateDraftAuditor.Snapshot snapshot = applyPublicationGate(
			scheme,
			runId,
			AllocationTemplateDraftAuditor.audit(
			entries,
			templateMapper.findTaskExpectations(scheme.getTaskId())
			)
		);
		List<List<AllocationTemplateAuditEntry>> occurrences = groupOccurrences(entries);
		List<AllocationItemView> views = new ArrayList<>(occurrences.size());
		for (List<AllocationTemplateAuditEntry> occurrence : occurrences) {
			AllocationTemplateAuditEntry entry = occurrence.get(0);
			List<String> messages = snapshot.messagesByFragment().getOrDefault(entry.getTemplateFragmentId(), List.of());
			AllocationItemView view = new AllocationItemView();
			// id 标识一次绝对周展示记录；编辑始终使用真实 templateFragmentId。
			view.setId(occurrenceId(entry.getTemplateFragmentId(), entry.getWeekNumber()));
			view.setTemplateFragmentId(entry.getTemplateFragmentId());
			view.setTemplateId(entry.getTemplateId());
			view.setFragmentCode(entry.getFragmentCode());
			view.setSchemeId(schemeId);
			view.setTeachingTaskId(entry.getTeachingTaskId());
			view.setCourseName(entry.getCourseName());
			view.setTeacherName(entry.getTeacherName());
			view.setClassGroupName(entry.getClassName());
			view.setClassroomId(entry.getClassroomId());
			view.setClassroomName(entry.getClassroomName());
			view.setWeekNumber(entry.getWeekNumber());
			view.setDayOfWeek(entry.getStartDayOfWeek());
			view.setPeriodIndex(entry.getStartPeriodIndex());
			view.setConsecutiveSlots(entry.getConsecutiveSlots());
			view.setDurationWeeks(entry.getDurationWeeks());
			view.setWeekNumbers(weeksByFragment.getOrDefault(entry.getTemplateFragmentId(), List.of(entry.getWeekNumber())));
			view.setSourceType(entry.getSourceType());
			view.setValid(messages.isEmpty());
			view.setConflictMessage(messages.isEmpty() ? null : String.join("；", messages));
			views.add(view);
		}
		return views;
	}

	public List<AllocationTemplateTimetableEntry> findWeekTimetable(
		Long allocationTaskId,
		String generationRunId,
		Integer weekNumber
	) {
		List<AllocationTemplateAuditEntry> weekEntries = templateMapper.findAuditEntriesByRun(allocationTaskId, generationRunId).stream()
			.filter(entry -> Objects.equals(weekNumber, entry.getWeekNumber()))
			.toList();
		return groupOccurrences(weekEntries).stream()
			.map(occurrence -> {
				AllocationTemplateAuditEntry entry = occurrence.get(0);
				AllocationTemplateTimetableEntry view = new AllocationTemplateTimetableEntry();
				view.setWeekNumber(entry.getWeekNumber());
				view.setTemplateId(entry.getTemplateId());
				view.setTemplateCode(entry.getTemplateCode());
				view.setTemplateFragmentId(entry.getTemplateFragmentId());
				view.setFragmentCode(entry.getFragmentCode());
				view.setTeachingTaskId(entry.getTeachingTaskId());
				view.setCourseName(entry.getCourseName());
				view.setTeacherIds(entry.getTeacherIds());
				view.setTeacherName(entry.getTeacherName());
				view.setClassGroupIds(entry.getClassGroupIds());
				view.setClassName(entry.getClassName());
				view.setClassroomId(entry.getClassroomId());
				view.setClassroomName(entry.getClassroomName());
				view.setDayOfWeek(entry.getStartDayOfWeek());
				view.setPeriodIndex(entry.getStartPeriodIndex());
				view.setRequiredRoomType(entry.getRequiredRoomType());
				view.setSourceType(entry.getSourceType());
				view.setConsecutiveSlots(entry.getConsecutiveSlots());
				view.setDurationWeeks(entry.getDurationWeeks());
				view.setStudentCount(entry.getStudentCount());
				view.setClassroomCapacity(entry.getClassroomCapacity());
				view.setClassroomType(entry.getClassroomType());
				return view;
			})
			.toList();
	}

	private List<List<AllocationTemplateAuditEntry>> groupOccurrences(List<AllocationTemplateAuditEntry> entries) {
		Map<String, List<AllocationTemplateAuditEntry>> grouped = entries.stream().collect(Collectors.groupingBy(
			entry -> entry.getTemplateFragmentId() + "|" + entry.getWeekNumber(),
			LinkedHashMap::new,
			Collectors.toList()
		));
		return grouped.values().stream()
			.peek(rows -> rows.sort(Comparator.comparing(AllocationTemplateAuditEntry::getPeriodIndex)))
			.sorted(Comparator
				.comparing((List<AllocationTemplateAuditEntry> rows) -> rows.get(0).getWeekNumber())
				.thenComparing(rows -> rows.get(0).getStartDayOfWeek())
				.thenComparing(rows -> rows.get(0).getStartPeriodIndex())
				.thenComparing(rows -> rows.get(0).getTemplateFragmentId()))
			.toList();
	}

	private long occurrenceId(Long fragmentId, Integer weekNumber) {
		long fragment = Objects.requireNonNullElse(fragmentId, 0L);
		long week = Objects.requireNonNullElse(weekNumber, 0);
		if (fragment <= (Long.MAX_VALUE - 99L) / 100L) return fragment * 100L + week;
		return (fragment & Long.MAX_VALUE) ^ week;
	}

	@Transactional
	public AllocationTemplateDraftView createFragment(
		Long schemeId,
		AllocationTemplateFragmentRequest request
	) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		String runId = generationRunId(scheme);
		AllocationTemplate template = requireTemplate(scheme, runId, request == null ? null : request.templateId());
		TeachingTask task = requireTask(scheme.getTaskId(), request == null ? null : request.teachingTaskId());
		Classroom classroom = requireClassroom(request == null ? null : request.classroomId());
		List<Integer> effectiveWeeks = resolveFragmentWeeks(scheme, runId, template, request, null);
		AllocationTemplateFragment fragment = buildFragment(scheme, runId, template, task, classroom, request, null, effectiveWeeks);
		if (templateMapper.insertFragment(fragment) != 1) {
			throw new ConflictException("模板片段新增失败");
		}
		insertFragmentWeeks(fragment, effectiveWeeks);
		insertRelationsAndSlots(fragment, task);
		markTemplateAdjusted(fragment);
		recordAdjustment(schemeId, fragment, null, fragment, request.reason(), "新增模板片段");
		return draftView(scheme, runId, auditSnapshot(scheme, runId, true));
	}

	@Transactional
	public AllocationTemplateDraftView updateFragment(
		Long schemeId,
		Long fragmentId,
		AllocationTemplateFragmentRequest request
	) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		String runId = generationRunId(scheme);
		AllocationTemplateFragment existing = requireFragment(scheme, runId, fragmentId);
		if (request == null) throw new ValidationException("模板片段调整请求不能为空");
		if (request.templateId() != null && !request.templateId().equals(existing.getTemplateId())) {
			throw new ValidationException("移动片段不能改变所属模板；请删除后在目标模板新增");
		}
		if (request.teachingTaskId() != null && !request.teachingTaskId().equals(existing.getTeachingTaskId())) {
			throw new ValidationException("移动片段不能替换教学任务；请删除后重新新增");
		}
		if (request.consecutiveSlots() != null && !request.consecutiveSlots().equals(existing.getConsecutiveSlots())) {
			throw new ValidationException("移动模板片段必须保留原连续节数；如需改单节/连排请删除后重新新增");
		}
		TeachingTask task = requireTask(scheme.getTaskId(), existing.getTeachingTaskId());
		Classroom classroom = requireClassroom(request.classroomId());
		AllocationTemplate template = requireTemplate(scheme, runId, existing.getTemplateId());
		List<Integer> effectiveWeeks = resolveFragmentWeeks(scheme, runId, template, request, existing);
		AllocationTemplateFragment updated = buildFragment(scheme, runId, template, task, classroom, request, existing, effectiveWeeks);
		if (templateMapper.updateFragmentPlacement(updated) != 1) {
			throw new ConflictException("模板片段更新失败");
		}
		templateMapper.deleteFragmentSlots(fragmentId);
		templateMapper.deleteFragmentTeachers(fragmentId);
		templateMapper.deleteFragmentClassGroups(fragmentId);
		templateMapper.deleteFragmentWeeks(fragmentId);
		insertFragmentWeeks(updated, effectiveWeeks);
		insertRelationsAndSlots(updated, task);
		markTemplateAdjusted(updated);
		recordAdjustment(schemeId, updated, existing, updated, request.reason(), "调整模板片段");
		return draftView(scheme, runId, auditSnapshot(scheme, runId, true));
	}

	@Transactional
	public AllocationTemplateDraftView moveFragmentFromLegacyRequest(
		Long schemeId,
		Long fragmentId,
		AllocationItemMoveRequest request
	) {
		if (request == null) throw new ValidationException("模板片段移动请求不能为空");
		TimeSlot slot = timeSlotService.findById(request.timeSlotId());
		AllocationTemplateFragment existing = requireFragmentForScheme(schemeId, fragmentId, true);
		return updateFragment(schemeId, fragmentId, new AllocationTemplateFragmentRequest(
			existing.getTemplateId(),
			existing.getTeachingTaskId(),
			request.classroomId(),
			slot.getDayOfWeek(),
			slot.getPeriodIndex(),
			existing.getConsecutiveSlots(),
			existing.getDurationWeeks(),
			null,
			request.reason()
		));
	}

	@Transactional
	public AllocationTemplateDraftView deleteFragment(Long schemeId, Long fragmentId, String reason) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		String runId = generationRunId(scheme);
		AllocationTemplateFragment fragment = requireFragment(scheme, runId, fragmentId);
		templateMapper.deleteFragmentSlots(fragmentId);
		templateMapper.deleteFragmentTeachers(fragmentId);
		templateMapper.deleteFragmentClassGroups(fragmentId);
		templateMapper.deleteFragmentWeeks(fragmentId);
		if (templateMapper.deleteFragment(fragmentId) != 1) {
			throw new ConflictException("模板片段删除失败");
		}
		markTemplateAdjusted(fragment);
		recordAdjustment(schemeId, fragment, fragment, null, reason, "删除模板片段");
		return draftView(scheme, runId, auditSnapshot(scheme, runId, true));
	}

	/**
	 * Accepts only non-hard review items (for example an explicitly excluded task,
	 * an irregular pattern, or an unavoidable 45-minute hour delta). The acceptance
	 * is fingerprinted against the current review reasons, so any material change
	 * automatically makes it stale and requires a new registrar decision.
	 */
	@Transactional
	public AllocationTemplateDraftView acceptManualReview(
		Long schemeId,
		AllocationTemplateManualReviewRequest request
	) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		if (request == null || !StringUtils.hasText(request.reason())) {
			throw new ValidationException("接受人工复核项时必须填写教务处理原因");
		}
		String reason = request.reason().trim();
		if (reason.length() > 500) throw new ValidationException("教务处理原因不能超过500字");
		String runId = generationRunId(scheme);
		AllocationTemplateDraftAuditor.Snapshot raw = rawAuditSnapshot(scheme, runId);
		List<String> gateHardBlockers = publicationGateHardBlockers(scheme);
		if (raw.result().hardConflictCount() > 0 || !gateHardBlockers.isEmpty()) {
			throw new ConflictException("仍存在不可豁免的硬约束问题，不能接受人工复核项");
		}
		List<String> pendingReasons = pendingManualReasons(scheme, raw.result());
		if (pendingReasons.isEmpty()) {
			throw new ValidationException("当前方案没有待接受的人工复核项");
		}

		Map<String, Object> summary = readSummary(scheme);
		List<Object> history = new ArrayList<>();
		Object existingHistory = summary.get("manual_review_acceptances");
		if (existingHistory instanceof List<?> existing) history.addAll(existing);
		Map<String, Object> acceptance = new LinkedHashMap<>();
		acceptance.put("generation_run_id", runId);
		acceptance.put("fingerprint", manualReviewFingerprint(runId, pendingReasons));
		acceptance.put("reason", reason);
		// Authentication is not wired in phase one, so never trust a client-supplied
		// actor name. Use an explicit server-side administrative identity.
		acceptance.put("accepted_by", "UNAUTHENTICATED_LOCAL_OPERATOR");
		acceptance.put("accepted_at", Instant.now().toString());
		acceptance.put("review_items", pendingReasons);
		history.add(acceptance);
		summary.put("manual_review_acceptances", history);
		try {
			String summaryJson = objectMapper.writeValueAsString(summary);
			if (schemeMapper.updateTemplateSummaryIfCandidate(schemeId, summaryJson) != 1) {
				throw new ConflictException("方案状态已变化，人工复核接受未保存");
			}
			scheme.setSummary(summaryJson);
		} catch (ConflictException exception) {
			throw exception;
		} catch (Exception exception) {
			throw new IllegalStateException("人工复核接受记录序列化失败", exception);
		}

		AllocationSchemeFeedback feedback = new AllocationSchemeFeedback();
		feedback.setSchemeId(schemeId);
		feedback.setTaskId(scheme.getTaskId());
		feedback.setFeedbackType("MANUAL_REVIEW_ACCEPTED");
		feedback.setAdjustmentCount(pendingReasons.size());
		feedback.setCreatedBy(String.valueOf(acceptance.get("accepted_by")));
		schemeFeedbackMapper.insert(feedback);

		AllocationTemplateDraftAuditor.Snapshot accepted = auditSnapshot(scheme, runId, true);
		return draftView(scheme, runId, accepted);
	}

	/** 确认服务调用：重新审计后返回每周一次课的正式物化源。 */
	@Transactional
	public List<AllocationTemplateSession> prepareMaterialization(Long schemeId) {
		AllocationScheme scheme = requireV35Scheme(schemeId, true);
		String runId = generationRunId(scheme);
		AllocationTemplateAuditResult audit = auditSnapshot(scheme, runId, true).result();
		if (!audit.valid()) {
			throw new ConflictException("V3.5模板草案尚未通过审计：" + audit.reviewStatus());
		}
		List<AllocationTemplateSession> sessions = templateMapper.findSessionsByRun(scheme.getTaskId(), runId);
		if (sessions.isEmpty()) throw new ValidationException("V3.5模板草案为空，不能确认");
		for (AllocationTemplateSession session : sessions) {
			if (session.getTeachingTaskId() == null || session.getClassroomId() == null || session.getTimeSlotId() == null) {
				throw new ConflictException("V3.5模板无法物化：片段#" + session.getTemplateFragmentId() + "缺少稳定ID或标准时间片");
			}
			if (session.getConsecutiveSlots() == null || session.getConsecutiveSlots() < 1 || session.getConsecutiveSlots() > 4) {
				throw new ConflictException("V3.5模板无法物化：片段#" + session.getTemplateFragmentId() + "连续节次数非法");
			}
		}
		return sessions;
	}

	private AllocationTemplateDraftAuditor.Snapshot auditSnapshot(
		AllocationScheme scheme,
		String runId,
		boolean persist
	) {
		AllocationTemplateDraftAuditor.Snapshot snapshot = applyPublicationGate(
			scheme,
			runId,
			rawAuditSnapshot(scheme, runId)
		);
		if (persist) persistAudit(scheme, runId, snapshot.result());
		return snapshot;
	}

	private AllocationTemplateDraftAuditor.Snapshot rawAuditSnapshot(AllocationScheme scheme, String runId) {
		return AllocationTemplateDraftAuditor.audit(
			templateMapper.findAuditEntriesByRun(scheme.getTaskId(), runId),
			templateMapper.findTaskExpectations(scheme.getTaskId())
		);
	}

	private AllocationTemplateDraftAuditor.Snapshot applyPublicationGate(
		AllocationScheme scheme,
		String runId,
		AllocationTemplateDraftAuditor.Snapshot raw
	) {
		AllocationTemplateAuditResult result = raw.result();
		List<String> hardBlockers = publicationGateHardBlockers(scheme);
		if (!hardBlockers.isEmpty()) {
			List<String> issues = new ArrayList<>(result.issues());
			hardBlockers.forEach(reason -> issues.add("生成链路发布闸门阻塞：" + reason));
			return new AllocationTemplateDraftAuditor.Snapshot(
				copyAuditResult(
					result,
					"BLOCKED",
					false,
					result.hardConflictCount() + hardBlockers.size(),
					result.identityIssueCount() + hardBlockers.size(),
					issues
				),
				raw.messagesByFragment()
			);
		}
		// Manual acceptance can only waive explicit hour/pattern/pipeline review
		// reasons. A later identity drift, malformed availability matrix, resource
		// conflict, capacity or room violation must always close the gate again.
		if (result.hardConflictCount() > 0) {
			return new AllocationTemplateDraftAuditor.Snapshot(
				copyAuditResult(
					result,
					"BLOCKED",
					false,
					result.hardConflictCount(),
					result.identityIssueCount(),
					result.issues()
				),
				raw.messagesByFragment()
			);
		}

		List<String> pendingReasons = pendingManualReasons(scheme, result);
		if (pendingReasons.isEmpty()) return raw;
		String fingerprint = manualReviewFingerprint(runId, pendingReasons);
		Map<?, ?> acceptance = findActiveManualReviewAcceptance(scheme, runId, fingerprint);
		List<String> issues = new ArrayList<>();
		if (acceptance == null) {
			pendingReasons.forEach(reason -> issues.add("待教务人工确认：" + reason));
			issues.addAll(result.issues());
			return new AllocationTemplateDraftAuditor.Snapshot(
				copyAuditResult(
					result,
					"NEEDS_MANUAL_REVIEW",
					false,
					result.hardConflictCount(),
					result.identityIssueCount(),
					issues
				),
				raw.messagesByFragment()
			);
		}

		issues.add(
			"人工复核项已由%s接受：%s".formatted(
				Objects.toString(acceptance.get("accepted_by"), "教务人工终审"),
				Objects.toString(acceptance.get("reason"), "已人工确认")
			)
		);
		pendingReasons.forEach(reason -> issues.add("已接受的人工复核项：" + reason));
		issues.addAll(result.issues());
		Map<Long, List<String>> filteredMessages = new LinkedHashMap<>();
		raw.messagesByFragment().forEach((fragmentId, messages) -> filteredMessages.put(
			fragmentId,
			messages.stream().filter(message -> !message.startsWith("课时不匹配：")).toList()
		));
		return new AllocationTemplateDraftAuditor.Snapshot(
			copyAuditResult(
				result,
				"COMPLETE_WITH_EXCEPTION",
				true,
				result.hardConflictCount(),
				result.identityIssueCount(),
				issues
			),
			filteredMessages
		);
	}

	private AllocationTemplateAuditResult copyAuditResult(
		AllocationTemplateAuditResult source,
		String reviewStatus,
		boolean valid,
		int hardConflictCount,
		int identityIssueCount,
		List<String> issues
	) {
		return new AllocationTemplateAuditResult(
			reviewStatus,
			valid,
			hardConflictCount,
			source.teacherConflictCount(),
			source.classGroupConflictCount(),
			source.classroomConflictCount(),
			source.capacityMismatchCount(),
			source.roomTypeMismatchCount(),
			identityIssueCount,
			source.hourMismatchTaskCount(),
			source.requiredTotalHours(),
			source.scheduledTotalHours(),
			source.deltaTotalHours(),
			source.taskHours(),
			List.copyOf(issues)
		);
	}

	private List<String> publicationGateHardBlockers(AllocationScheme scheme) {
		Map<String, Object> summary = readSummary(scheme);
		List<String> blockers = stringList(summary.get("publication_gate_hard_blockers"));
		if (blockers.isEmpty() && "BLOCKED".equalsIgnoreCase(Objects.toString(
			summary.get("publication_gate_status"), ""
		))) {
			return List.of("生成链路标记为BLOCKED，但未提供具体阻塞原因");
		}
		return blockers;
	}

	private List<String> pendingManualReasons(
		AllocationScheme scheme,
		AllocationTemplateAuditResult audit
	) {
		Map<String, Object> summary = readSummary(scheme);
		var reasons = new java.util.LinkedHashSet<String>(
			stringList(summary.get("publication_gate_manual_reviews"))
		);
		if (reasons.isEmpty() && "NEEDS_MANUAL_REVIEW".equalsIgnoreCase(Objects.toString(
			summary.get("publication_gate_status"), ""
		))) {
			reasons.add("生成链路要求人工复核，但未提供具体原因");
		}
		for (AllocationTemplateTaskHourAudit task : audit.taskHours()) {
			if ("OK".equals(task.status())) continue;
			reasons.add(
				"教学任务#%d %s课时为%d/%d（%+d）".formatted(
					task.teachingTaskId(),
					StringUtils.hasText(task.courseName()) ? task.courseName() + " " : "",
					task.scheduledHours(),
					task.requiredHours(),
					task.deltaHours()
				)
			);
		}
		return List.copyOf(reasons);
	}

	private Map<?, ?> findActiveManualReviewAcceptance(
		AllocationScheme scheme,
		String runId,
		String fingerprint
	) {
		Object rawHistory = readSummary(scheme).get("manual_review_acceptances");
		if (!(rawHistory instanceof List<?> history)) return null;
		for (int index = history.size() - 1; index >= 0; index--) {
			if (!(history.get(index) instanceof Map<?, ?> acceptance)) continue;
			if (Objects.equals(runId, Objects.toString(acceptance.get("generation_run_id"), null))
				&& Objects.equals(fingerprint, Objects.toString(acceptance.get("fingerprint"), null))) {
				return acceptance;
			}
		}
		return null;
	}

	private String manualReviewFingerprint(String runId, List<String> pendingReasons) {
		String canonical = runId + "\n" + pendingReasons.stream().sorted().collect(Collectors.joining("\n"));
		try {
			return HexFormat.of().formatHex(
				MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8))
			);
		} catch (Exception exception) {
			throw new IllegalStateException("无法生成复核项指纹", exception);
		}
	}

	private List<String> stringList(Object value) {
		if (!(value instanceof List<?> list)) return List.of();
		return list.stream()
			.map(item -> Objects.toString(item, "").trim())
			.filter(StringUtils::hasText)
			.distinct()
			.toList();
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> readSummary(AllocationScheme scheme) {
		if (scheme == null || !StringUtils.hasText(scheme.getSummary())) return new LinkedHashMap<>();
		try {
			return new LinkedHashMap<>(objectMapper.readValue(scheme.getSummary(), Map.class));
		} catch (Exception exception) {
			throw new ValidationException("V3.5方案摘要无法解析，不能执行发布审计");
		}
	}

	@SuppressWarnings("unchecked")
	private void persistAudit(AllocationScheme scheme, String runId, AllocationTemplateAuditResult audit) {
		Map<String, Object> summary = new LinkedHashMap<>();
		if (StringUtils.hasText(scheme.getSummary())) {
			try {
				summary.putAll(objectMapper.readValue(scheme.getSummary(), Map.class));
			} catch (Exception e) {
				log.warn("V3.5 scheme summary is malformed, rebuilding it: schemeId={}", scheme.getId());
			}
		}
		long underTasks = audit.taskHours().stream().filter(row -> "UNDER".equals(row.status())).count();
		summary.put("generation_run_id", runId);
		summary.put("review_status", audit.reviewStatus());
		summary.put("requires_manual_review", "NEEDS_MANUAL_REVIEW".equals(audit.reviewStatus()));
		summary.put("hard_blocked", "BLOCKED".equals(audit.reviewStatus()));
		summary.put("manual_review_acceptance_active", "COMPLETE_WITH_EXCEPTION".equals(audit.reviewStatus()));
		summary.put("unplaced_task_count", underTasks);
		summary.put("hour_mismatch_task_count", audit.hourMismatchTaskCount());
		summary.put("hard_conflict_count", audit.hardConflictCount());
		summary.put("capacity_mismatch_count", audit.capacityMismatchCount());
		summary.put("required_total_hours", audit.requiredTotalHours());
		summary.put("scheduled_total_hours", audit.scheduledTotalHours());
		summary.put("delta_total_hours", audit.deltaTotalHours());

		Map<String, Object> conflictSummary = new LinkedHashMap<>();
		conflictSummary.put("review_status", audit.reviewStatus());
		conflictSummary.put("hard_conflict_count", audit.hardConflictCount());
		conflictSummary.put("teacher_conflict_count", audit.teacherConflictCount());
		conflictSummary.put("class_group_conflict_count", audit.classGroupConflictCount());
		conflictSummary.put("classroom_conflict_count", audit.classroomConflictCount());
		conflictSummary.put("capacity_mismatch_count", audit.capacityMismatchCount());
		conflictSummary.put("room_type_mismatch_count", audit.roomTypeMismatchCount());
		conflictSummary.put("identity_issue_count", audit.identityIssueCount());
		conflictSummary.put("conservation_mismatch", audit.hourMismatchTaskCount());
		conflictSummary.put("publication_gate_status", summary.get("publication_gate_status"));
		conflictSummary.put(
			"publication_gate_hard_blockers",
			stringList(summary.get("publication_gate_hard_blockers"))
		);
		conflictSummary.put(
			"publication_gate_manual_reviews",
			stringList(summary.get("publication_gate_manual_reviews"))
		);
		conflictSummary.put("manual_review_acceptance_active", "COMPLETE_WITH_EXCEPTION".equals(audit.reviewStatus()));
		conflictSummary.put("issues", audit.issues().stream().limit(100).toList());
		try {
			String summaryJson = objectMapper.writeValueAsString(summary);
			if (schemeMapper.updateTemplateReviewState(
				scheme.getId(),
				summaryJson,
				audit.valid(),
				objectMapper.writeValueAsString(conflictSummary)
			) != 1) {
				throw new ConflictException("方案状态已变化，审计结果未保存");
			}
			scheme.setSummary(summaryJson);
			scheme.setValid(audit.valid());
			scheme.setConflictSummary(objectMapper.writeValueAsString(conflictSummary));
		} catch (Exception e) {
			throw new IllegalStateException("V3.5模板审计结果序列化失败", e);
		}
	}

	private List<AllocationTemplateDraftTemplate> findDraftTemplates(Long taskId, String runId) {
		Map<Long, List<Integer>> weeksByTemplate = templateMapper.findTemplateWeeksByRun(taskId, runId).stream()
			.collect(Collectors.groupingBy(
				AllocationTemplateWeek::getTemplateId,
				LinkedHashMap::new,
				Collectors.mapping(AllocationTemplateWeek::getWeekNumber, Collectors.toList())
			));
		return templateMapper.findTemplatesByRun(taskId, runId).stream()
			.map(template -> new AllocationTemplateDraftTemplate(
				template.getId(),
				template.getTemplateCode(),
				template.getTemplateName(),
				Objects.requireNonNullElse(template.getFragmentCount(), 0),
				Objects.requireNonNullElse(template.getTaskCount(), 0),
				weeksByTemplate.getOrDefault(template.getId(), List.of()).stream().sorted().toList()
			))
			.toList();
	}

	private AllocationTemplateFragment buildFragment(
		AllocationScheme scheme,
		String runId,
		AllocationTemplate template,
		TeachingTask task,
		Classroom classroom,
		AllocationTemplateFragmentRequest request,
		AllocationTemplateFragment existing,
		List<Integer> effectiveWeeks
	) {
		if (request == null) throw new ValidationException("模板片段请求不能为空");
		Integer day = request.dayOfWeek();
		Integer period = request.periodIndex();
		if (day == null || day < 1 || day > 7) throw new ValidationException("星期必须在1到7之间");
		if (period == null || period < 1 || period > 10) throw new ValidationException("节次必须在1到10之间");
		String courseType = task.getCourse() == null ? null : task.getCourse().getCourseType();
		int defaultPeriods = TeachingSessionTimePolicy.periodCount(courseType);
		if (defaultPeriods == 0) throw new ValidationException("课程类型缺失或不支持，无法构造模板片段");
		int consecutive = request.consecutiveSlots() != null
			? request.consecutiveSlots()
			: existing != null && existing.getConsecutiveSlots() != null
				? existing.getConsecutiveSlots() : defaultPeriods;
		if (consecutive != 1 && consecutive != defaultPeriods) {
			throw new ValidationException(courseType + "模板片段默认连续" + defaultPeriods + "节，人工仅可显式补1节");
		}
		if (consecutive > 1 && !TeachingSessionTimePolicy.isLegalStartPeriod(period, consecutive)) {
			throw new ValidationException("连续" + consecutive + "节的合法起点是" + TeachingSessionTimePolicy.legalStartDescription(consecutive));
		}
		if (consecutive == 1 && period > 10) throw new ValidationException("人工单节课必须位于1到10节");
		int duration = effectiveWeeks.size();

		List<ClassGroup> classGroups = task.getClassGroups() == null ? List.of() : task.getClassGroups();
		Teacher primary = task.getPrimaryTeacher();
		String primaryName = primary == null ? null : primary.getName();
		String classNames = classGroups.stream().map(ClassGroup::getName).filter(StringUtils::hasText).collect(Collectors.joining("、"));
		AllocationTemplateFragment fragment = existing == null ? new AllocationTemplateFragment() : copyFragment(existing);
		fragment.setTemplateId(template.getId());
		fragment.setTemplateCode(template.getTemplateCode());
		fragment.setAllocationTaskId(scheme.getTaskId());
		fragment.setGenerationRunId(runId);
		if (existing == null) {
			fragment.setFragmentCode("manual:" + UUID.randomUUID());
			fragment.setTeachingTaskId(task.getId());
			fragment.setSourceKey("teaching-task:" + task.getId());
			fragment.setCourseId(task.getCourseId());
			fragment.setCourseName(task.getCourse() == null ? null : task.getCourse().getName());
			fragment.setTeacherId(task.getPrimaryTeacherId());
			fragment.setTeacherName(primaryName);
			fragment.setClassGroupId(classGroups.size() == 1 ? classGroups.get(0).getId() : null);
			fragment.setClassName(classNames);
			fragment.setRequiredRoomType(StringUtils.hasText(task.getRequiredRoomType())
				? task.getRequiredRoomType()
				: task.getCourse() == null ? null : task.getCourse().getRequiredRoomType());
			fragment.setLockStatus("UNLOCKED");
			fragment.setSourceType("MANUAL");
		}
		fragment.setClassroomId(classroom.getId());
		fragment.setClassroomName(classroom.getName());
		fragment.setDayOfWeek(day);
		fragment.setPeriodIndex(period);
		fragment.setConsecutiveSlots(consecutive);
		fragment.setDurationWeeks(duration);
		fragment.setSessionHours(consecutive);
		return fragment;
	}

	private List<Integer> resolveFragmentWeeks(
		AllocationScheme scheme,
		String runId,
		AllocationTemplate template,
		AllocationTemplateFragmentRequest request,
		AllocationTemplateFragment existing
	) {
		List<Integer> mappedWeeks = templateMapper.findTemplateWeeksByRun(scheme.getTaskId(), runId).stream()
			.filter(week -> Objects.equals(template.getId(), week.getTemplateId()))
			.map(AllocationTemplateWeek::getWeekNumber)
			.filter(Objects::nonNull)
			.distinct()
			.sorted()
			.toList();
		if (mappedWeeks.isEmpty()) throw new ValidationException("动态模板没有映射到任何教学周");

		if (request.weekNumbers() != null) {
			List<Integer> requested = request.weekNumbers().stream()
				.filter(Objects::nonNull)
				.distinct()
				.sorted()
				.toList();
			if (requested.isEmpty()) throw new ValidationException("模板片段必须至少选择一个生效周次");
			if (!mappedWeeks.containsAll(requested)) {
				throw new ValidationException("模板片段生效周次必须全部属于所选动态模板：" + mappedWeeks);
			}
			return requested;
		}

		if (existing != null) {
			List<Integer> stored = templateMapper.findFragmentWeeksByRun(scheme.getTaskId(), runId).stream()
				.filter(week -> Objects.equals(existing.getId(), week.getTemplateFragmentId()))
				.map(AllocationTemplateFragmentWeek::getWeekNumber)
				.filter(mappedWeeks::contains)
				.distinct()
				.sorted()
				.toList();
			if (!stored.isEmpty()) return stored;
		}

		int legacyDuration = request.durationWeeks() != null
			? request.durationWeeks()
			: existing != null && existing.getDurationWeeks() != null
				? existing.getDurationWeeks() : mappedWeeks.size();
		int clampedDuration = existing != null
			? Math.min(Math.max(1, legacyDuration), mappedWeeks.size())
			: legacyDuration;
		if (clampedDuration < 1 || clampedDuration > mappedWeeks.size()) {
			throw new ValidationException("生效周数必须在1到该模板覆盖周数" + mappedWeeks.size() + "之间");
		}
		return mappedWeeks.subList(0, clampedDuration);
	}

	private void insertFragmentWeeks(AllocationTemplateFragment fragment, List<Integer> weekNumbers) {
		for (Integer weekNumber : weekNumbers) {
			templateMapper.insertFragmentWeek(
				fragment.getId(),
				fragment.getAllocationTaskId(),
				fragment.getGenerationRunId(),
				fragment.getTemplateId(),
				weekNumber
			);
		}
	}

	private void insertRelationsAndSlots(AllocationTemplateFragment fragment, TeachingTask task) {
		if (task.getPrimaryTeacherId() != null) {
			templateMapper.insertFragmentTeacher(
				fragment.getId(), fragment.getFragmentCode(), fragment.getTemplateId(), fragment.getTemplateCode(),
				fragment.getAllocationTaskId(), fragment.getGenerationRunId(), fragment.getTeachingTaskId(),
				task.getPrimaryTeacherId(), "PRIMARY"
			);
		}
		if (task.getAssistantTeacherId() != null && !task.getAssistantTeacherId().equals(task.getPrimaryTeacherId())) {
			templateMapper.insertFragmentTeacher(
				fragment.getId(), fragment.getFragmentCode(), fragment.getTemplateId(), fragment.getTemplateCode(),
				fragment.getAllocationTaskId(), fragment.getGenerationRunId(), fragment.getTeachingTaskId(),
				task.getAssistantTeacherId(), "ASSISTANT"
			);
		}
		if (task.getClassGroups() != null) {
			for (ClassGroup classGroup : task.getClassGroups()) {
				if (classGroup.getId() == null) continue;
				templateMapper.insertFragmentClassGroup(
					fragment.getId(), fragment.getFragmentCode(), fragment.getTemplateId(), fragment.getTemplateCode(),
					fragment.getAllocationTaskId(), fragment.getGenerationRunId(), fragment.getTeachingTaskId(), classGroup.getId()
				);
			}
		}
		insertSlots(fragment, task);
	}

	private void insertSlots(AllocationTemplateFragment fragment, TeachingTask task) {
		Long scalarClassGroup = task.getClassGroups() != null && task.getClassGroups().size() == 1
			? task.getClassGroups().get(0).getId() : null;
		for (int offset = 0; offset < fragment.getConsecutiveSlots(); offset++) {
			templateMapper.insertFragmentSlot(
				fragment.getId(), fragment.getFragmentCode(), fragment.getTemplateId(), fragment.getTemplateCode(),
				fragment.getAllocationTaskId(), fragment.getGenerationRunId(), fragment.getTeachingTaskId(),
				fragment.getClassroomId(), task.getPrimaryTeacherId(), scalarClassGroup,
				fragment.getDayOfWeek(), fragment.getPeriodIndex() + offset
			);
		}
	}

	private void markTemplateAdjusted(AllocationTemplateFragment fragment) {
		templateMapper.refreshTemplateCounts(fragment.getTemplateId());
		templateMapper.markTemplateWeeksAdjusted(
			fragment.getAllocationTaskId(), fragment.getGenerationRunId(), fragment.getTemplateId()
		);
	}

	private void recordAdjustment(
		Long schemeId,
		AllocationTemplateFragment reference,
		AllocationTemplateFragment before,
		AllocationTemplateFragment after,
		String reason,
		String fallbackReason
	) {
		Integer firstWeek = templateMapper.findTemplateWeeksByRun(
			reference.getAllocationTaskId(), reference.getGenerationRunId()
		).stream()
			.filter(week -> Objects.equals(week.getTemplateId(), reference.getTemplateId()))
			.map(AllocationTemplateWeek::getWeekNumber)
			.min(Comparator.naturalOrder())
			.orElse(null);
		Long fromTimeSlotId = before == null || firstWeek == null ? null
			: templateMapper.findTimeSlotId(firstWeek, before.getDayOfWeek(), before.getPeriodIndex());
		Long toTimeSlotId = after == null || firstWeek == null ? null
			: templateMapper.findTimeSlotId(firstWeek, after.getDayOfWeek(), after.getPeriodIndex());
		AllocationItemAdjustmentLog adjustment = new AllocationItemAdjustmentLog();
		adjustment.setSchemeId(schemeId);
		adjustment.setItemId(reference.getId());
		adjustment.setTeachingTaskId(reference.getTeachingTaskId());
		adjustment.setFromTimeSlotId(fromTimeSlotId);
		adjustment.setToTimeSlotId(toTimeSlotId);
		adjustment.setFromClassroomId(before == null ? null : before.getClassroomId());
		adjustment.setToClassroomId(after == null ? null : after.getClassroomId());
		adjustment.setReason(StringUtils.hasText(reason) ? reason.trim() : fallbackReason);
		adjustmentLogMapper.insert(adjustment);
		if (before != null && after != null) {
			feedbackEventService.recordItemMoved(
				schemeId,
				feedbackItem(schemeId, before, fromTimeSlotId),
				feedbackItem(schemeId, after, toTimeSlotId),
				adjustment.getId(),
				adjustment.getReason()
			);
		}
	}

	private AllocationItem feedbackItem(Long schemeId, AllocationTemplateFragment fragment, Long timeSlotId) {
		AllocationItem item = new AllocationItem();
		item.setId(fragment.getId());
		item.setSchemeId(schemeId);
		item.setTeachingTaskId(fragment.getTeachingTaskId());
		item.setClassroomId(fragment.getClassroomId());
		item.setTimeSlotId(timeSlotId);
		return item;
	}

	private AllocationTemplateFragment requireFragmentForScheme(Long schemeId, Long fragmentId, boolean editable) {
		AllocationScheme scheme = requireV35Scheme(schemeId, editable);
		return requireFragment(scheme, generationRunId(scheme), fragmentId);
	}

	private AllocationTemplateFragment requireFragment(AllocationScheme scheme, String runId, Long fragmentId) {
		Assert.positiveId(fragmentId, "模板片段ID");
		AllocationTemplateFragment fragment = templateMapper.findFragmentByRun(scheme.getTaskId(), runId, fragmentId);
		if (fragment == null) throw new ResourceNotFoundException("V3.5模板片段不存在或不属于该方案批次");
		if ("LOCKED".equalsIgnoreCase(fragment.getLockStatus())) throw new ConflictException("该模板片段已锁定，不能人工调整");
		return fragment;
	}

	private AllocationTemplate requireTemplate(AllocationScheme scheme, String runId, Long templateId) {
		Assert.positiveId(templateId, "模板ID");
		AllocationTemplate template = templateMapper.findTemplateByRun(scheme.getTaskId(), runId, templateId);
		if (template == null) throw new ResourceNotFoundException("模板不存在或不属于该方案批次");
		return template;
	}

	private TeachingTask requireTask(Long allocationTaskId, Long teachingTaskId) {
		Assert.positiveId(teachingTaskId, "教学任务ID");
		if (templateMapper.countTaskMembership(allocationTaskId, teachingTaskId) != 1) {
			throw new ValidationException("教学任务不属于当前排课任务");
		}
		TeachingTask task = teachingTaskMapper.findWithDetails(teachingTaskId);
		if (task == null) throw new ResourceNotFoundException("教学任务不存在");
		return task;
	}

	private Classroom requireClassroom(Long classroomId) {
		Assert.positiveId(classroomId, "教室ID");
		Classroom classroom = classroomMapper.findById(classroomId);
		if (classroom == null) throw new ResourceNotFoundException("教室不存在");
		if (classroom.getStatus() != null && !"ACTIVE".equals(classroom.getStatus().code())) {
			throw new ValidationException("只能使用启用状态的教室");
		}
		return classroom;
	}

	private AllocationScheme requireV35Scheme(Long schemeId, boolean editable) {
		Assert.positiveId(schemeId, "分课方案ID");
		AllocationScheme scheme = editable ? schemeMapper.findByIdForUpdate(schemeId) : schemeMapper.findById(schemeId);
		if (scheme == null) throw new ResourceNotFoundException("分课方案不存在");
		if (!isV35(scheme)) throw new ValidationException("该接口只适用于V3.5模板方案");
		if (editable && scheme.getStatus() != SchemeStatus.CANDIDATE) {
			throw new ConflictException("只有候选状态的V3.5模板方案可以人工编辑");
		}
		return scheme;
	}

	@SuppressWarnings("unchecked")
	public String generationRunId(AllocationScheme scheme) {
		if (scheme == null || !StringUtils.hasText(scheme.getSummary())) {
			throw new ValidationException("V3.5方案缺少生成批次信息");
		}
		try {
			Map<String, Object> summary = objectMapper.readValue(scheme.getSummary(), Map.class);
			Object runId = summary.get("generation_run_id");
			if (runId == null || !StringUtils.hasText(String.valueOf(runId))) {
				throw new ValidationException("V3.5方案未绑定生成批次，不能编辑或确认");
			}
			return String.valueOf(runId).trim();
		} catch (ValidationException e) {
			throw e;
		} catch (Exception e) {
			throw new ValidationException("V3.5方案生成批次信息无法解析");
		}
	}

	private AllocationTemplateFragment copyFragment(AllocationTemplateFragment source) {
		AllocationTemplateFragment copy = new AllocationTemplateFragment();
		copy.setId(source.getId());
		copy.setTemplateId(source.getTemplateId());
		copy.setTemplateCode(source.getTemplateCode());
		copy.setAllocationTaskId(source.getAllocationTaskId());
		copy.setGenerationRunId(source.getGenerationRunId());
		copy.setFragmentCode(source.getFragmentCode());
		copy.setTeachingTaskId(source.getTeachingTaskId());
		copy.setSourceKey(source.getSourceKey());
		copy.setCourseId(source.getCourseId());
		copy.setCourseName(source.getCourseName());
		copy.setTeacherId(source.getTeacherId());
		copy.setTeacherName(source.getTeacherName());
		copy.setClassGroupId(source.getClassGroupId());
		copy.setClassName(source.getClassName());
		copy.setClassroomId(source.getClassroomId());
		copy.setClassroomName(source.getClassroomName());
		copy.setDayOfWeek(source.getDayOfWeek());
		copy.setPeriodIndex(source.getPeriodIndex());
		copy.setConsecutiveSlots(source.getConsecutiveSlots());
		copy.setDurationWeeks(source.getDurationWeeks());
		copy.setSessionHours(source.getSessionHours());
		copy.setRequiredRoomType(source.getRequiredRoomType());
		copy.setSourceType(source.getSourceType());
		copy.setLockStatus(source.getLockStatus());
		return copy;
	}
}
