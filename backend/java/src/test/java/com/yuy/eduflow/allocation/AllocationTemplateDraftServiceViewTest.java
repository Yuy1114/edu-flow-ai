package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.enums.ActiveStatus;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.ObjectMapper;

@ExtendWith(MockitoExtension.class)
class AllocationTemplateDraftServiceViewTest {
	@Mock private AllocationSchemeMapper schemeMapper;
	@Mock private AllocationTemplateMapper templateMapper;
	@Mock private TeachingTaskMapper teachingTaskMapper;
	@Mock private ClassroomMapper classroomMapper;
	@Mock private TimeSlotService timeSlotService;
	@Mock private AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	@Mock private AllocationSchemeFeedbackMapper schemeFeedbackMapper;
	@Mock private MlFeedbackEventService feedbackEventService;

	private AllocationTemplateDraftService service;

	@BeforeEach
	void setUp() {
		service = new AllocationTemplateDraftService(
			schemeMapper, templateMapper, teachingTaskMapper, classroomMapper, timeSlotService,
			adjustmentLogMapper, schemeFeedbackMapper, feedbackEventService, new ObjectMapper()
		);
	}

	@Test
	void collapsesAtomicRowsIntoOneStableOccurrencePerFragmentAndWeek() {
		AllocationScheme scheme = new AllocationScheme();
		scheme.setId(7L);
		scheme.setTaskId(8L);
		scheme.setModelVersion("v3.5-dynamic-week");
		scheme.setSummary("{\"generation_run_id\":\"run-1\"}");
		when(schemeMapper.findById(7L)).thenReturn(scheme);
		when(templateMapper.findAuditEntriesByRun(8L, "run-1")).thenReturn(List.of(
			entry(20L, 1, 1), entry(20L, 1, 2), entry(20L, 2, 1), entry(20L, 2, 2)
		));
		AllocationTemplateTaskExpectation expectation = new AllocationTemplateTaskExpectation();
		expectation.setTeachingTaskId(30L);
		expectation.setCourseName("软件工程");
		expectation.setRequiredHours(4);
		expectation.setSessionPeriods(2);
		expectation.setTeachingTaskStatus("ACTIVE");
		expectation.setCourseStatus("ACTIVE");
		when(templateMapper.findTaskExpectations(8L)).thenReturn(List.of(expectation));

		List<AllocationItemView> views = service.findSchemeItems(7L);

		assertEquals(2, views.size());
		assertEquals(List.of(1, 2), views.stream().map(AllocationItemView::getWeekNumber).toList());
		assertEquals(20L, views.get(0).getTemplateFragmentId());
		assertEquals(1, views.get(0).getPeriodIndex());
		verify(schemeMapper, never()).updateTemplateReviewState(any(), any(), any(), any());
	}

	@Test
	void draftReadsArePureAndCannotOverwriteAManualAcceptanceSummary() {
		AllocationScheme scheme = v35Scheme();
		scheme.setSummary("{\"generation_run_id\":\"run-1\",\"manual_review_acceptances\":[{\"reason\":\"保留\"}]}");
		when(schemeMapper.findById(7L)).thenReturn(scheme);

		service.findDraft(7L);
		service.findSchemeItems(7L);

		verify(schemeMapper, never()).updateTemplateReviewState(any(), any(), any(), any());
		verify(schemeMapper, never()).updateTemplateSummaryIfCandidate(any(), any());
	}

	@Test
	void movesAFragmentToTheExactSelectedWeekInsteadOfTheFirstMappedWeeks() {
		AllocationScheme scheme = v35Scheme();
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(schemeMapper.updateTemplateReviewState(any(), any(), any(), any())).thenReturn(1);

		AllocationTemplateFragment existing = fragment();
		when(templateMapper.findFragmentByRun(8L, "run-1", 20L)).thenReturn(existing);
		when(templateMapper.countTaskMembership(8L, 30L)).thenReturn(1);
		when(teachingTaskMapper.findWithDetails(30L)).thenReturn(teachingTask());
		when(classroomMapper.findById(4L)).thenReturn(classroom());
		AllocationTemplate template = new AllocationTemplate();
		template.setId(10L);
		template.setTemplateCode("dynamic-1");
		when(templateMapper.findTemplateByRun(8L, "run-1", 10L)).thenReturn(template);
		when(templateMapper.findTemplateWeeksByRun(8L, "run-1")).thenReturn(List.of(templateWeek(2), templateWeek(10)));
		when(templateMapper.updateFragmentPlacement(any())).thenReturn(1);

		service.updateFragment(7L, 20L, new AllocationTemplateFragmentRequest(
			10L, 30L, 4L, 2, 3, 2, 2, List.of(10), "只调整第10周"
		));

		ArgumentCaptor<AllocationTemplateFragment> fragmentCaptor = ArgumentCaptor.forClass(AllocationTemplateFragment.class);
		verify(templateMapper).updateFragmentPlacement(fragmentCaptor.capture());
		assertEquals(1, fragmentCaptor.getValue().getDurationWeeks());
		verify(templateMapper).insertFragmentWeek(20L, 8L, "run-1", 10L, 10);
		verify(templateMapper, never()).insertFragmentWeek(20L, 8L, "run-1", 10L, 2);
	}

	@Test
	void recordsServerOwnedManualAcceptanceAndAReauditCanPublishWithException() {
		AllocationScheme scheme = v35Scheme();
		scheme.setSummary("{\"generation_run_id\":\"run-1\",\"publication_gate_status\":\"NEEDS_MANUAL_REVIEW\",\"publication_gate_manual_reviews\":[\"特殊尾差\"]}");
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(schemeMapper.updateTemplateSummaryIfCandidate(any(), any())).thenReturn(1);
		when(schemeMapper.updateTemplateReviewState(any(), any(), any(), any())).thenReturn(1);

		AllocationTemplateDraftView accepted = service.acceptManualReview(
			7L, new AllocationTemplateManualReviewRequest("教务确认用晚间单节补足")
		);

		assertEquals("COMPLETE_WITH_EXCEPTION", accepted.audit().reviewStatus());
		assertTrue(accepted.audit().valid());
		assertTrue(scheme.getSummary().contains("UNAUTHENTICATED_LOCAL_OPERATOR"));
		assertTrue(scheme.getSummary().contains("教务确认用晚间单节补足"));
		assertTrue(scheme.getSummary().contains("fingerprint"));
		assertTrue(scheme.getSummary().contains("特殊尾差"));
	}

	@Test
	void oldManualAcceptanceCanNeverWashOutANewHardIdentityDrift() {
		AllocationScheme scheme = v35Scheme();
		scheme.setSummary("{\"generation_run_id\":\"run-1\",\"publication_gate_status\":\"NEEDS_MANUAL_REVIEW\",\"publication_gate_manual_reviews\":[\"特殊尾差\"]}");
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(schemeMapper.findById(7L)).thenReturn(scheme);
		when(schemeMapper.updateTemplateSummaryIfCandidate(any(), any())).thenReturn(1);
		when(schemeMapper.updateTemplateReviewState(any(), any(), any(), any())).thenReturn(1);
		AllocationTemplateAuditEntry drift = entry(20L, 1, 1);
		drift.setConsecutiveSlots(1);
		drift.setExpectedSessionPeriods(2);
		drift.setTeacherRelationsCurrent(false);
		when(templateMapper.findAuditEntriesByRun(8L, "run-1"))
			.thenReturn(List.of(), List.of(), List.of(drift));

		AllocationTemplateDraftView accepted = service.acceptManualReview(
			7L, new AllocationTemplateManualReviewRequest("先接受尾差")
		);
		AllocationTemplateDraftView afterDrift = service.findDraft(7L);

		assertEquals("COMPLETE_WITH_EXCEPTION", accepted.audit().reviewStatus());
		assertEquals("BLOCKED", afterDrift.audit().reviewStatus());
		assertFalse(afterDrift.audit().valid());
		assertTrue(afterDrift.audit().hardConflictCount() > 0);
	}

	private AllocationScheme v35Scheme() {
		AllocationScheme scheme = new AllocationScheme();
		scheme.setId(7L);
		scheme.setTaskId(8L);
		scheme.setStatus(com.yuy.eduflow.enums.SchemeStatus.CANDIDATE);
		scheme.setModelVersion("v3.5-dynamic-week");
		scheme.setSummary("{\"generation_run_id\":\"run-1\"}");
		return scheme;
	}

	private AllocationTemplateFragment fragment() {
		AllocationTemplateFragment fragment = new AllocationTemplateFragment();
		fragment.setId(20L);
		fragment.setTemplateId(10L);
		fragment.setTemplateCode("dynamic-1");
		fragment.setAllocationTaskId(8L);
		fragment.setGenerationRunId("run-1");
		fragment.setFragmentCode("fragment-20");
		fragment.setTeachingTaskId(30L);
		fragment.setClassroomId(4L);
		fragment.setDayOfWeek(1);
		fragment.setPeriodIndex(1);
		fragment.setConsecutiveSlots(2);
		fragment.setDurationWeeks(2);
		fragment.setSourceType("MANUAL");
		fragment.setLockStatus("UNLOCKED");
		return fragment;
	}

	private TeachingTask teachingTask() {
		Course course = new Course();
		course.setId(50L);
		course.setName("软件工程");
		course.setCourseType("理论课");
		course.setRequiredRoomType("普通教室");
		Teacher teacher = new Teacher();
		teacher.setId(1L);
		teacher.setName("教师A");
		ClassGroup group = new ClassGroup();
		group.setId(2L);
		group.setName("软件1班");
		group.setStudentCount(50);
		TeachingTask task = new TeachingTask();
		task.setId(30L);
		task.setCourseId(50L);
		task.setCourse(course);
		task.setPrimaryTeacherId(1L);
		task.setPrimaryTeacher(teacher);
		task.setClassGroups(List.of(group));
		task.setStatus(ActiveStatus.ACTIVE);
		return task;
	}

	private Classroom classroom() {
		Classroom classroom = new Classroom();
		classroom.setId(4L);
		classroom.setName("A101");
		classroom.setCapacity(120);
		classroom.setClassroomType("普通教室");
		classroom.setStatus(ActiveStatus.ACTIVE);
		return classroom;
	}

	private AllocationTemplateWeek templateWeek(int weekNumber) {
		AllocationTemplateWeek week = new AllocationTemplateWeek();
		week.setAllocationTaskId(8L);
		week.setGenerationRunId("run-1");
		week.setTemplateId(10L);
		week.setTemplateCode("dynamic-1");
		week.setWeekNumber(weekNumber);
		return week;
	}

	private AllocationTemplateAuditEntry entry(Long fragmentId, int week, int period) {
		AllocationTemplateAuditEntry entry = new AllocationTemplateAuditEntry();
		entry.setWeekNumber(week);
		entry.setTemplateId(10L);
		entry.setTemplateFragmentId(fragmentId);
		entry.setTeachingTaskId(30L);
		entry.setCourseName("软件工程");
		entry.setCourseType("理论课");
		entry.setExpectedSessionPeriods(2);
		entry.setTeacherIds("1");
		entry.setTeacherName("教师A");
		entry.setClassGroupIds("2,3");
		entry.setClassName("软件1班、软件2班");
		entry.setClassroomId(4L);
		entry.setClassroomName("A101");
		entry.setClassroomCapacity(120);
		entry.setClassroomType("普通教室");
		entry.setClassroomStatus("ACTIVE");
		entry.setStudentCount(100);
		entry.setDayOfWeek(1);
		entry.setPeriodIndex(period);
		entry.setStartDayOfWeek(1);
		entry.setStartPeriodIndex(1);
		entry.setConsecutiveSlots(2);
		entry.setDurationWeeks(2);
		entry.setTeachingTaskStatus("ACTIVE");
		entry.setCourseStatus("ACTIVE");
		entry.setPrimaryTeacherStatus("ACTIVE");
		entry.setTeacherHardUnavailable(false);
		entry.setClassroomAllowed(true);
		entry.setRequiredRoomType("普通教室");
		return entry;
	}
}
