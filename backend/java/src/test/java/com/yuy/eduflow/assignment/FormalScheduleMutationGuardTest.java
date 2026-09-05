package com.yuy.eduflow.assignment;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.common.exception.ConflictException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class FormalScheduleMutationGuardTest {
	@Mock CourseAssignmentMapper mapper;

	@Test
	void locksPublicationAndFreezesResourcesUsedByAnActiveFormalAssignment() {
		when(mapper.countActiveByTeacher(9L)).thenReturn(1);
		FormalScheduleMutationGuard guard = new FormalScheduleMutationGuard(mapper);

		assertThrows(ConflictException.class, () -> guard.lockAndRejectTeacher(9L));

		InOrder order = inOrder(mapper);
		order.verify(mapper).lockSchedulePublication();
		order.verify(mapper).countActiveByTeacher(9L);
	}
}
