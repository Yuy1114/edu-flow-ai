package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class AllocationTemplateDraftAuditorTest {

	@Test
	void countsAtomicSlotsExactlyOnceAndAcceptsAnExplicitManualSinglePeriod() {
		AllocationTemplateTaskExpectation theory = expectation(10L, 3, 2);
		List<AllocationTemplateAuditEntry> entries = List.of(
			entry(1L, 10L, 1, 1, 1, 2, 1, "1,2", "11,12", 100L),
			entry(1L, 10L, 1, 1, 2, 2, 1, "1,2", "11,12", 100L),
			entry(2L, 10L, 2, 3, 9, 1, 9, "1,2", "11,12", 101L)
		);

		AllocationTemplateAuditResult result = AllocationTemplateDraftAuditor.audit(entries, List.of(theory)).result();

		assertEquals("COMPLETE", result.reviewStatus());
		assertEquals(3, result.scheduledTotalHours());
		assertEquals(0, result.hourMismatchTaskCount());
		assertTrue(result.valid());
	}

	@Test
	void catchesAssistantTeacherOverlapAndPostGenerationHardConstraintChanges() {
		AllocationTemplateAuditEntry first = entry(1L, 10L, 1, 1, 1, 1, 1, "1,2", "11", 100L);
		AllocationTemplateAuditEntry second = entry(2L, 20L, 1, 1, 1, 1, 1, "2,3", "12", 101L);
		second.setTeacherHardUnavailable(true);
		second.setClassroomAllowed(false);
		second.setClassroomStatus("INACTIVE");

		AllocationTemplateAuditResult result = AllocationTemplateDraftAuditor.audit(
			List.of(first, second),
			List.of(expectation(10L, 1, 2), expectation(20L, 1, 2))
		).result();

		assertEquals("BLOCKED", result.reviewStatus());
		assertEquals(1, result.teacherConflictCount());
		assertTrue(result.identityIssueCount() >= 3);
		assertFalse(result.valid());
	}

	@Test
	void rejectsAJsonObjectOrWrongShapeAsAnInvalidTeacherAvailabilityMatrix() {
		AllocationTemplateAuditEntry invalid = entry(1L, 10L, 1, 1, 1, 1, 1, "1", "11", 100L);
		invalid.setPrimaryAvailabilityMatrixJson("{}");

		AllocationTemplateAuditResult result = AllocationTemplateDraftAuditor.audit(
			List.of(invalid),
			List.of(expectation(10L, 1, 2))
		).result();

		assertEquals("BLOCKED", result.reviewStatus());
		assertTrue(result.issues().stream().anyMatch(issue -> issue.contains("可用性矩阵非法")));
	}

	@Test
	void blocksAFragmentWhenItsCourseWasDisabledAfterGeneration() {
		AllocationTemplateAuditEntry inactiveCourse = entry(
			1L, 10L, 1, 1, 1, 1, 1, "1", "11", 100L
		);
		inactiveCourse.setCourseStatus("INACTIVE");

		AllocationTemplateAuditResult result = AllocationTemplateDraftAuditor.audit(
			List.of(inactiveCourse),
			List.of(expectation(10L, 1, 2))
		).result();

		assertEquals("BLOCKED", result.reviewStatus());
		assertTrue(result.issues().stream().anyMatch(issue -> issue.contains("课程不是启用状态")));
	}

	@Test
	void blocksAnInactiveExpectedCourseEvenWhenTheTaskHasNoFragment() {
		AllocationTemplateTaskExpectation inactive = expectation(10L, 2, 2);
		inactive.setCourseStatus("INACTIVE");

		AllocationTemplateAuditResult result = AllocationTemplateDraftAuditor.audit(
			List.of(),
			List.of(inactive)
		).result();

		assertEquals("BLOCKED", result.reviewStatus());
		assertTrue(result.issues().stream().anyMatch(issue -> issue.contains("关联课程不是启用状态")));
	}

	private AllocationTemplateTaskExpectation expectation(Long id, int hours, int sessionPeriods) {
		AllocationTemplateTaskExpectation result = new AllocationTemplateTaskExpectation();
		result.setTeachingTaskId(id);
		result.setCourseName("课程" + id);
		result.setRequiredHours(hours);
		result.setCourseType("理论课");
		result.setSessionPeriods(sessionPeriods);
		result.setTeachingTaskStatus("ACTIVE");
		result.setCourseStatus("ACTIVE");
		return result;
	}

	private AllocationTemplateAuditEntry entry(
		Long fragmentId,
		Long taskId,
		int week,
		int day,
		int period,
		int consecutive,
		int start,
		String teacherIds,
		String classIds,
		Long roomId
	) {
		AllocationTemplateAuditEntry result = new AllocationTemplateAuditEntry();
		result.setWeekNumber(week);
		result.setTemplateId(9L);
		result.setTemplateFragmentId(fragmentId);
		result.setFragmentCode("f" + fragmentId);
		result.setTeachingTaskId(taskId);
		result.setCourseName("课程" + taskId);
		result.setCourseType("理论课");
		result.setExpectedSessionPeriods(2);
		result.setTeacherIds(teacherIds);
		result.setTeacherName("教师" + teacherIds);
		result.setClassGroupIds(classIds);
		result.setClassName("班级" + classIds);
		result.setClassroomId(roomId);
		result.setClassroomName("教室" + roomId);
		result.setClassroomCapacity(80);
		result.setClassroomType("普通教室");
		result.setClassroomStatus("ACTIVE");
		result.setStudentCount(60);
		result.setDayOfWeek(day);
		result.setPeriodIndex(period);
		result.setStartDayOfWeek(day);
		result.setStartPeriodIndex(start);
		result.setConsecutiveSlots(consecutive);
		result.setDurationWeeks(1);
		result.setTeachingTaskStatus("ACTIVE");
		result.setCourseStatus("ACTIVE");
		result.setPrimaryTeacherStatus("ACTIVE");
		result.setTeacherHardUnavailable(false);
		result.setClassroomAllowed(true);
		result.setRequiredRoomType("普通教室");
		return result;
	}
}
