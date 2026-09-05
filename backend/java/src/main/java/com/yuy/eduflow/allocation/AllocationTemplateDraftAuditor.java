package com.yuy.eduflow.allocation;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.teacher.AvailabilityMatrixPolicy;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

/** V3.5 草案的唯一审计器，所有人工编辑和最终确认都复用这里。 */
public final class AllocationTemplateDraftAuditor {
	private static final ObjectMapper AVAILABILITY_OBJECT_MAPPER = new ObjectMapper();

	private AllocationTemplateDraftAuditor() {
	}

	public static Snapshot audit(
		List<AllocationTemplateAuditEntry> entries,
		List<AllocationTemplateTaskExpectation> expectations
	) {
		List<AllocationTemplateAuditEntry> safeEntries = entries == null ? List.of() : entries;
		List<AllocationTemplateTaskExpectation> safeExpectations = expectations == null ? List.of() : expectations;
		IssueCollector collector = new IssueCollector();

		collectIdentityIssues(safeEntries, collector);
		collectStructureIssues(safeEntries, collector);
		collectResourceConflicts(safeEntries, "教师", AllocationTemplateAuditEntry::getTeacherIds, collector.teacherIssues, collector);
		collectResourceConflicts(safeEntries, "班级", AllocationTemplateAuditEntry::getClassGroupIds, collector.classIssues, collector);
		collectResourceConflicts(
			safeEntries,
			"教室",
			entry -> entry.getClassroomId() == null ? null : String.valueOf(entry.getClassroomId()),
			collector.classroomIssues,
			collector
		);
		collectCapacityAndRoomTypeIssues(safeEntries, collector);

		Map<Long, Integer> scheduledByTask = new LinkedHashMap<>();
		Map<Long, Set<Long>> fragmentsByTask = new LinkedHashMap<>();
		for (AllocationTemplateAuditEntry entry : safeEntries) {
			if (entry.getTeachingTaskId() == null) continue;
			scheduledByTask.merge(entry.getTeachingTaskId(), 1, Integer::sum);
			if (entry.getTemplateFragmentId() != null) {
				fragmentsByTask.computeIfAbsent(entry.getTeachingTaskId(), ignored -> new LinkedHashSet<>())
					.add(entry.getTemplateFragmentId());
			}
		}

		Set<Long> expectedTaskIds = new HashSet<>();
		List<AllocationTemplateTaskHourAudit> hourAudits = new ArrayList<>();
		int requiredTotal = 0;
		int scheduledTotal = 0;
		int mismatchCount = 0;
		for (AllocationTemplateTaskExpectation expectation : safeExpectations) {
			Long taskId = expectation.getTeachingTaskId();
			if (taskId == null) continue;
			expectedTaskIds.add(taskId);
			if (!"ACTIVE".equalsIgnoreCase(expectation.getTeachingTaskStatus())) {
				String key = "expected-task-status|" + taskId;
				collector.identityIssues.add(key);
				collector.addGeneral(key, "教学任务#%d不是启用状态，候选方案不可发布".formatted(taskId));
			}
			if (!"ACTIVE".equalsIgnoreCase(expectation.getCourseStatus())) {
				String key = "expected-course-status|" + taskId;
				collector.identityIssues.add(key);
				collector.addGeneral(key, "教学任务#%d关联课程不是启用状态，候选方案不可发布".formatted(taskId));
			}
			int required = Math.max(0, Objects.requireNonNullElse(expectation.getRequiredHours(), 0));
			int scheduled = scheduledByTask.getOrDefault(taskId, 0);
			int delta = scheduled - required;
			requiredTotal += required;
			scheduledTotal += scheduled;
			String status = delta == 0 ? "OK" : delta < 0 ? "UNDER" : "OVER";
			if (delta != 0) {
				mismatchCount++;
				String message = "课时不匹配：教学任务#%d %s应排%d课时，当前%d课时（%+d）".formatted(
					taskId,
					StringUtils.hasText(expectation.getCourseName()) ? expectation.getCourseName() : "",
					required,
					scheduled,
					delta
				);
				collector.addGeneral("hours|" + taskId, message);
				for (Long fragmentId : fragmentsByTask.getOrDefault(taskId, Set.of())) {
					collector.addFragmentMessage(fragmentId, message);
				}
			}
			hourAudits.add(new AllocationTemplateTaskHourAudit(
				taskId,
				expectation.getCourseName(),
				required,
				scheduled,
				delta,
				Math.max(0, Objects.requireNonNullElse(expectation.getSessionPeriods(), 0)),
				status
			));
		}

		for (Map.Entry<Long, Integer> actual : scheduledByTask.entrySet()) {
			if (expectedTaskIds.contains(actual.getKey())) continue;
			String message = "模板包含不属于当前排课任务的教学任务#" + actual.getKey();
			if (collector.identityIssues.add("unexpected-task|" + actual.getKey())) {
				collector.addGeneral("unexpected-task|" + actual.getKey(), message);
			}
			for (Long fragmentId : fragmentsByTask.getOrDefault(actual.getKey(), Set.of())) {
				collector.addFragmentMessage(fragmentId, message);
			}
		}

		int hardConflictCount = collector.teacherIssues.size()
			+ collector.classIssues.size()
			+ collector.classroomIssues.size()
			+ collector.capacityIssues.size()
			+ collector.roomTypeIssues.size()
			+ collector.identityIssues.size();
		String reviewStatus = hardConflictCount > 0
			? "BLOCKED"
			: mismatchCount > 0 ? "NEEDS_MANUAL_REVIEW" : "COMPLETE";
		AllocationTemplateAuditResult result = new AllocationTemplateAuditResult(
			reviewStatus,
			"COMPLETE".equals(reviewStatus),
			hardConflictCount,
			collector.teacherIssues.size(),
			collector.classIssues.size(),
			collector.classroomIssues.size(),
			collector.capacityIssues.size(),
			collector.roomTypeIssues.size(),
			collector.identityIssues.size(),
			mismatchCount,
			requiredTotal,
			scheduledTotal,
			scheduledTotal - requiredTotal,
			List.copyOf(hourAudits),
			List.copyOf(collector.generalMessages.values())
		);
		return new Snapshot(result, collector.fragmentMessages());
	}

	private static void collectIdentityIssues(
		List<AllocationTemplateAuditEntry> entries,
		IssueCollector collector
	) {
		for (AllocationTemplateAuditEntry entry : entries) {
			Long fragmentId = entry.getTemplateFragmentId();
			if (fragmentId == null) continue;
			if (entry.getTeachingTaskId() == null) {
				collector.addIdentity(fragmentId, "teaching-task", "模板片段#%d缺少稳定教学任务ID".formatted(fragmentId));
			}
			if (!StringUtils.hasText(entry.getTeacherIds())) {
				collector.addIdentity(fragmentId, "teachers", "模板片段#%d缺少教师关系".formatted(fragmentId));
			}
			if (!StringUtils.hasText(entry.getClassGroupIds())) {
				collector.addIdentity(fragmentId, "classes", "模板片段#%d缺少班级关系".formatted(fragmentId));
			}
			if (entry.getClassroomId() == null || entry.getClassroomCapacity() == null) {
				collector.addIdentity(fragmentId, "classroom", "模板片段#%d缺少有效教室或容量".formatted(fragmentId));
			}
			if (!"ACTIVE".equalsIgnoreCase(entry.getTeachingTaskStatus())) {
				collector.addIdentity(fragmentId, "task-status", "模板片段#%d引用的教学任务不是启用状态".formatted(fragmentId));
			}
			if (!"ACTIVE".equalsIgnoreCase(entry.getCourseStatus())) {
				collector.addIdentity(fragmentId, "course-status", "模板片段#%d引用的课程不是启用状态".formatted(fragmentId));
			}
			if (!"ACTIVE".equalsIgnoreCase(entry.getPrimaryTeacherStatus())
				|| (StringUtils.hasText(entry.getAssistantTeacherStatus())
					&& !"ACTIVE".equalsIgnoreCase(entry.getAssistantTeacherStatus()))) {
				collector.addIdentity(fragmentId, "teacher-status", "模板片段#%d引用了停用教师".formatted(fragmentId));
			}
			if (!"ACTIVE".equalsIgnoreCase(entry.getClassroomStatus())) {
				collector.addIdentity(fragmentId, "classroom-status", "模板片段#%d引用的教室不是启用状态".formatted(fragmentId));
			}
			if (Boolean.FALSE.equals(entry.getClassroomAllowed())) {
				collector.addIdentity(
					fragmentId,
					"classroom-candidate",
					"模板片段#%d使用的教室不在教学任务固定/候选教室范围内".formatted(fragmentId)
				);
			}
			if (Boolean.FALSE.equals(entry.getTeacherRelationsCurrent())) {
				collector.addIdentity(
					fragmentId,
					"teacher-relations",
					"模板片段#%d的教师关系已与当前教学任务不一致，请重新保存该片段".formatted(fragmentId)
				);
			}
			if (Boolean.FALSE.equals(entry.getClassGroupRelationsCurrent())) {
				collector.addIdentity(
					fragmentId,
					"class-relations",
					"模板片段#%d的班级关系已与当前教学任务不一致，请重新保存该片段".formatted(fragmentId)
				);
			}
			collectAvailabilityIssue(
				entry,
				entry.getPrimaryAvailabilityMatrixJson(),
				"主讲教师",
				collector
			);
			collectAvailabilityIssue(
				entry,
				entry.getAssistantAvailabilityMatrixJson(),
				"协作教师",
				collector
			);
			if (Boolean.TRUE.equals(entry.getTeacherHardUnavailable())) {
				collector.addIdentity(
					fragmentId,
					"teacher-unavailable|" + entry.getWeekNumber() + '|' + entry.getDayOfWeek() + '|' + entry.getPeriodIndex(),
					"教师不可用：模板片段#%d在第%d周 周%d 第%d节命中教师硬禁排".formatted(
						fragmentId, entry.getWeekNumber(), entry.getDayOfWeek(), entry.getPeriodIndex()
					)
				);
			}
			if (entry.getWeekNumber() == null || entry.getWeekNumber() < 1
				|| entry.getDayOfWeek() == null || entry.getDayOfWeek() < 1 || entry.getDayOfWeek() > 7
				|| entry.getPeriodIndex() == null || entry.getPeriodIndex() < 1 || entry.getPeriodIndex() > 10) {
				collector.addIdentity(fragmentId, "time", "模板片段#%d包含非法绝对周时间坐标".formatted(fragmentId));
			}
		}
	}

	private static void collectAvailabilityIssue(
		AllocationTemplateAuditEntry entry,
		String matrixJson,
		String teacherRole,
		IssueCollector collector
	) {
		if (!StringUtils.hasText(matrixJson)
			|| entry.getTemplateFragmentId() == null
			|| entry.getDayOfWeek() == null
			|| entry.getPeriodIndex() == null) {
			return;
		}
		try {
			if (AvailabilityMatrixPolicy.isHardUnavailable(
				AVAILABILITY_OBJECT_MAPPER,
				matrixJson,
				entry.getDayOfWeek(),
				entry.getPeriodIndex()
			)) {
				collector.addIdentity(
					entry.getTemplateFragmentId(),
					"teacher-unavailable|" + entry.getWeekNumber() + '|' + entry.getDayOfWeek() + '|' + entry.getPeriodIndex(),
					"教师不可用：模板片段#%d在第%d周 周%d 第%d节命中教师硬禁排".formatted(
						entry.getTemplateFragmentId(), entry.getWeekNumber(), entry.getDayOfWeek(), entry.getPeriodIndex()
					)
				);
			}
		} catch (ValidationException exception) {
			collector.addIdentity(
				entry.getTemplateFragmentId(),
				"teacher-availability-shape|" + teacherRole,
				"模板片段#%d的%s可用性矩阵非法：%s".formatted(
					entry.getTemplateFragmentId(), teacherRole, exception.getMessage()
				)
			);
		}
	}

	private static void collectStructureIssues(
		List<AllocationTemplateAuditEntry> entries,
		IssueCollector collector
	) {
		Map<String, List<AllocationTemplateAuditEntry>> occurrences = entries.stream()
			.filter(entry -> entry.getTemplateFragmentId() != null && entry.getWeekNumber() != null)
			.collect(Collectors.groupingBy(
				entry -> entry.getTemplateFragmentId() + "|" + entry.getWeekNumber(),
				LinkedHashMap::new,
				Collectors.toList()
			));
		for (List<AllocationTemplateAuditEntry> occurrence : occurrences.values()) {
			AllocationTemplateAuditEntry first = occurrence.get(0);
			Long fragmentId = first.getTemplateFragmentId();
			int consecutive = Objects.requireNonNullElse(first.getConsecutiveSlots(), 0);
			int expected = Objects.requireNonNullElse(first.getExpectedSessionPeriods(), 0);
			int start = Objects.requireNonNullElse(first.getStartPeriodIndex(), 0);
			int startDay = Objects.requireNonNullElse(first.getStartDayOfWeek(), 0);
			if (consecutive != 1 && consecutive != expected) {
				collector.addIdentity(
					fragmentId,
					"span",
					"模板片段#%d连续节次数%d与课程类型%s不匹配（仅允许默认%d节或人工1节）".formatted(
						fragmentId, consecutive, Objects.toString(first.getCourseType(), "未知"), expected
					)
				);
			}
			if (consecutive < 1 || (consecutive > 1 && !TeachingSessionTimePolicy.isLegalStartPeriod(start, consecutive))) {
				collector.addIdentity(fragmentId, "start", "模板片段#%d起始节次或连续跨度非法".formatted(fragmentId));
			}
			Set<Integer> actualPeriods = occurrence.stream()
				.filter(entry -> Objects.equals(startDay, entry.getDayOfWeek()))
				.map(AllocationTemplateAuditEntry::getPeriodIndex)
				.filter(Objects::nonNull)
				.collect(Collectors.toCollection(LinkedHashSet::new));
			Set<Integer> expectedPeriods = new LinkedHashSet<>();
			for (int offset = 0; offset < consecutive; offset++) expectedPeriods.add(start + offset);
			if (startDay < 1 || startDay > 7 || !actualPeriods.equals(expectedPeriods)) {
				collector.addIdentity(
					fragmentId,
					"slot-expansion|" + first.getWeekNumber(),
					"模板片段#%d在第%d周的原子节次展开不完整：应为%s，实际为%s".formatted(
						fragmentId, first.getWeekNumber(), expectedPeriods, actualPeriods
					)
				);
			}
		}
	}

	private static void collectResourceConflicts(
		List<AllocationTemplateAuditEntry> entries,
		String label,
		Function<AllocationTemplateAuditEntry, String> extractor,
		Set<String> issueSet,
		IssueCollector collector
	) {
		Map<String, Set<Long>> fragmentsBySlot = new LinkedHashMap<>();
		Map<String, String> resourceLabels = new LinkedHashMap<>();
		for (AllocationTemplateAuditEntry entry : entries) {
			if (entry.getTemplateFragmentId() == null) continue;
			for (String resourceId : splitIds(extractor.apply(entry))) {
				String key = resourceId + '|' + entry.getWeekNumber() + '|' + entry.getDayOfWeek() + '|' + entry.getPeriodIndex();
				fragmentsBySlot.computeIfAbsent(key, ignored -> new LinkedHashSet<>()).add(entry.getTemplateFragmentId());
				resourceLabels.putIfAbsent(key, switch (label) {
					case "教师" -> entry.getTeacherName();
					case "班级" -> entry.getClassName();
					default -> entry.getClassroomName();
				});
			}
		}
		for (Map.Entry<String, Set<Long>> bucket : fragmentsBySlot.entrySet()) {
			if (bucket.getValue().size() <= 1) continue;
			String issueKey = label + '|' + bucket.getKey();
			issueSet.add(issueKey);
			String[] parts = bucket.getKey().split("\\|");
			String message = "%s冲突：%s在第%s周 周%s 第%s节被%d个片段同时占用".formatted(
				label,
				Objects.toString(resourceLabels.get(bucket.getKey()), parts[0]),
				parts[1], parts[2], parts[3], bucket.getValue().size()
			);
			collector.addGeneral(issueKey, message);
			for (Long fragmentId : bucket.getValue()) {
				collector.addFragmentMessage(fragmentId, message);
			}
		}
	}

	private static void collectCapacityAndRoomTypeIssues(
		List<AllocationTemplateAuditEntry> entries,
		IssueCollector collector
	) {
		Set<String> visited = new HashSet<>();
		for (AllocationTemplateAuditEntry entry : entries) {
			Long fragmentId = entry.getTemplateFragmentId();
			if (fragmentId == null) continue;
			String occurrence = fragmentId + "|" + entry.getWeekNumber();
			if (!visited.add(occurrence)) continue;
			int students = Math.max(0, Objects.requireNonNullElse(entry.getStudentCount(), 0));
			int capacity = Math.max(0, Objects.requireNonNullElse(entry.getClassroomCapacity(), 0));
			if (students > capacity) {
				String message = "容量不足：%s需容纳%d人，教室%s容量%d".formatted(
					Objects.toString(entry.getCourseName(), "教学任务#" + entry.getTeachingTaskId()),
					students,
					Objects.toString(entry.getClassroomName(), "#" + entry.getClassroomId()),
					capacity
				);
				String key = "capacity|" + occurrence;
				collector.capacityIssues.add(key);
				collector.addGeneral(key, message);
				collector.addFragmentMessage(fragmentId, message);
			}
			String requiredType = normalizeRoomType(entry.getRequiredRoomType());
			String actualType = normalizeRoomType(entry.getClassroomType());
			if (StringUtils.hasText(requiredType) && !requiredType.equals(actualType)) {
				String message = "教室类型不匹配：%s需要%s，当前为%s".formatted(
					Objects.toString(entry.getCourseName(), "教学任务#" + entry.getTeachingTaskId()),
					requiredType,
					StringUtils.hasText(actualType) ? actualType : "未标注"
				);
				String key = "room-type|" + occurrence;
				collector.roomTypeIssues.add(key);
				collector.addGeneral(key, message);
				collector.addFragmentMessage(fragmentId, message);
			}
		}
	}

	private static String normalizeRoomType(String value) {
		if (!StringUtils.hasText(value)) return null;
		String normalized = value.trim();
		if (normalized.contains("机房") || normalized.contains("计算机")) return "机房";
		if (normalized.contains("普通") || normalized.contains("教室")) return "普通教室";
		return normalized;
	}

	private static Collection<String> splitIds(String csv) {
		if (!StringUtils.hasText(csv)) return List.of();
		List<String> values = new ArrayList<>();
		for (String raw : csv.split(",")) {
			String value = raw.trim();
			if (!value.isEmpty() && !values.contains(value)) values.add(value);
		}
		return values;
	}

	public record Snapshot(
		AllocationTemplateAuditResult result,
		Map<Long, List<String>> messagesByFragment
	) {
	}

	private static final class IssueCollector {
		private final Set<String> teacherIssues = new LinkedHashSet<>();
		private final Set<String> classIssues = new LinkedHashSet<>();
		private final Set<String> classroomIssues = new LinkedHashSet<>();
		private final Set<String> capacityIssues = new LinkedHashSet<>();
		private final Set<String> roomTypeIssues = new LinkedHashSet<>();
		private final Set<String> identityIssues = new LinkedHashSet<>();
		private final Map<String, String> generalMessages = new LinkedHashMap<>();
		private final Map<Long, LinkedHashSet<String>> messagesByFragment = new LinkedHashMap<>();

		private void addIdentity(Long fragmentId, String field, String message) {
			String key = "identity|" + fragmentId + '|' + field;
			identityIssues.add(key);
			addGeneral(key, message);
			addFragmentMessage(fragmentId, message);
		}

		private void addGeneral(String key, String message) {
			generalMessages.putIfAbsent(key, message);
		}

		private void addFragmentMessage(Long fragmentId, String message) {
			messagesByFragment.computeIfAbsent(fragmentId, ignored -> new LinkedHashSet<>()).add(message);
		}

		private Map<Long, List<String>> fragmentMessages() {
			Map<Long, List<String>> result = new LinkedHashMap<>();
			messagesByFragment.forEach((key, value) -> result.put(key, List.copyOf(value)));
			return Map.copyOf(result);
		}
	}
}
