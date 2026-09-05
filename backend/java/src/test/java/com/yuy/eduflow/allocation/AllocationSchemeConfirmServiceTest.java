package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.assignment.CourseAssignmentMapper;
import com.yuy.eduflow.assignment.CourseAssignmentService;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.SchemeStatus;
import com.yuy.eduflow.enums.TaskStatus;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AllocationSchemeConfirmServiceTest {
	@Mock AllocationSchemeMapper schemeMapper;
	@Mock AllocationItemMapper itemMapper;
	@Mock AllocationTaskMapper taskMapper;
	@Mock CourseAssignmentMapper assignmentMapper;
	@Mock AllocationSchemeFeedbackMapper feedbackMapper;
	@Mock AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	@Mock MlFeedbackEventService feedbackEventService;
	@Mock AllocationTemplateDraftService draftService;
	@Mock CourseAssignmentService assignmentService;

	private AllocationSchemeConfirmService service;

	@BeforeEach
	void setUp() {
		service = new AllocationSchemeConfirmService(
			schemeMapper, itemMapper, taskMapper, assignmentMapper, feedbackMapper,
			adjustmentLogMapper, feedbackEventService, draftService, assignmentService
		);
	}

	@Test
	void serializesReauditsAgainstTheGlobalFormalTimetableAndUsesCompareAndSetStates() {
		AllocationScheme scheme = scheme(SchemeStatus.CANDIDATE);
		AllocationTask task = task(TaskStatus.GENERATED);
		AllocationTemplateSession session = session();
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(taskMapper.findByIdForUpdate(8L)).thenReturn(task);
		when(draftService.isV35(scheme)).thenReturn(true);
		when(draftService.prepareMaterialization(7L)).thenReturn(List.of(session));
		when(assignmentMapper.insert(org.mockito.ArgumentMatchers.any())).thenReturn(1);
		when(schemeMapper.updateStatusIfCurrent(7L, "CANDIDATE", "CONFIRMED")).thenReturn(1);
		when(taskMapper.updateStatusIfCurrent(8L, "GENERATED", "CONFIRMED")).thenReturn(1);

		AllocationConfirmResult result = service.confirm(7L);

		assertEquals(1, result.assignmentCount());
		InOrder order = inOrder(assignmentMapper, schemeMapper, taskMapper, draftService, assignmentService);
		order.verify(assignmentMapper).lockSchedulePublication();
		order.verify(schemeMapper).findByIdForUpdate(7L);
		order.verify(taskMapper).findByIdForUpdate(8L);
		order.verify(draftService).prepareMaterialization(7L);
		order.verify(assignmentMapper).inactivateByAllocationTaskId(8L, "INACTIVE");
		order.verify(assignmentService).validateForPublication(org.mockito.ArgumentMatchers.any());
		order.verify(assignmentMapper).insert(org.mockito.ArgumentMatchers.any());
		order.verify(schemeMapper).updateStatusIfCurrent(7L, "CANDIDATE", "CONFIRMED");
	}

	@Test
	void rejectsNonCandidateSchemesAndRunningTasks() {
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme(SchemeStatus.REJECTED));
		assertThrows(ValidationException.class, () -> service.confirm(7L));
		verify(taskMapper, never()).findByIdForUpdate(8L);

		AllocationScheme candidate = scheme(SchemeStatus.CANDIDATE);
		when(schemeMapper.findByIdForUpdate(9L)).thenReturn(candidate);
		when(taskMapper.findByIdForUpdate(8L)).thenReturn(task(TaskStatus.RUNNING));
		assertThrows(ValidationException.class, () -> service.confirm(9L));
		verify(draftService, never()).prepareMaterialization(9L);
	}

	@Test
	void rollsBackBeforeInsertWhenAnotherFormalTimetableConflicts() {
		AllocationScheme scheme = scheme(SchemeStatus.CANDIDATE);
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(taskMapper.findByIdForUpdate(8L)).thenReturn(task(TaskStatus.GENERATED));
		when(draftService.isV35(scheme)).thenReturn(true);
		when(draftService.prepareMaterialization(7L)).thenReturn(List.of(session()));
		org.mockito.Mockito.doThrow(new ConflictException("external conflict"))
			.when(assignmentService).validateForPublication(org.mockito.ArgumentMatchers.any());

		assertThrows(ConflictException.class, () -> service.confirm(7L));

		verify(assignmentMapper, never()).insert(org.mockito.ArgumentMatchers.any());
		verify(schemeMapper, never()).updateStatusIfCurrent(7L, "CANDIDATE", "CONFIRMED");
	}

	@Test
	void rejectsTheLegacyValidItemBypassEvenForAGeneratedTask() {
		AllocationScheme legacy = scheme(SchemeStatus.CANDIDATE);
		legacy.setModelVersion("legacy");
		when(schemeMapper.findByIdForUpdate(7L)).thenReturn(legacy);
		when(taskMapper.findByIdForUpdate(8L)).thenReturn(task(TaskStatus.GENERATED));
		when(draftService.isV35(legacy)).thenReturn(false);

		assertThrows(ValidationException.class, () -> service.confirm(7L));

		verify(itemMapper, never()).findAll(
			org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(),
			org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any()
		);
		verify(assignmentMapper, never()).insert(org.mockito.ArgumentMatchers.any());
	}

	private AllocationScheme scheme(SchemeStatus status) {
		AllocationScheme scheme = new AllocationScheme();
		scheme.setId(status == SchemeStatus.REJECTED ? 7L : 7L);
		scheme.setTaskId(8L);
		scheme.setStatus(status);
		scheme.setModelVersion("v3.5-dynamic-week");
		return scheme;
	}

	private AllocationTask task(TaskStatus status) {
		AllocationTask task = new AllocationTask();
		task.setId(8L);
		task.setStatus(status);
		return task;
	}

	private AllocationTemplateSession session() {
		AllocationTemplateSession session = new AllocationTemplateSession();
		session.setTeachingTaskId(10L);
		session.setClassroomId(20L);
		session.setTimeSlotId(30L);
		session.setConsecutiveSlots(2);
		return session;
	}
}
