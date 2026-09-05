package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import com.yuy.eduflow.classroom.ClassroomService;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.conflict.ConflictCheckResultMapper;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlotService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.ObjectMapper;

@ExtendWith(MockitoExtension.class)
class AllocationItemServiceTimeBlockTest {

	@Mock private AllocationItemMapper allocationItemMapper;
	@Mock private AllocationSchemeConflictDetector conflictDetector;
	@Mock private AllocationSchemeMapper allocationSchemeMapper;
	@Mock private AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	@Mock private ConflictCheckResultMapper conflictCheckResultMapper;
	@Mock private ClassroomService classroomService;
	@Mock private TimeSlotService timeSlotService;
	@Mock private TeachingTaskMapper teachingTaskMapper;
	@Mock private TeacherProfileMapper teacherProfileMapper;
	@Mock private ObjectMapper objectMapper;
	@Mock private MlFeedbackEventService feedbackEventService;

	private AllocationItemService service;

	@BeforeEach
	void setUp() {
		service = new AllocationItemService(
			allocationItemMapper,
			conflictDetector,
			allocationSchemeMapper,
			adjustmentLogMapper,
			conflictCheckResultMapper,
			classroomService,
			timeSlotService,
			teachingTaskMapper,
			teacherProfileMapper,
			objectMapper,
			feedbackEventService
		);
	}

	@Test
	void rejectsAllLegacyAllocationItemMovesBeforeReadingOrWritingLegacyRows() {
		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(1L, 2L, new AllocationItemMoveRequest(20L, 1003L, null))
		);

		assertEquals("第一阶段旧版allocation_item链路只读；请使用V3.5模板草案片段接口编辑和重审计", exception.getMessage());
		verify(allocationItemMapper, never()).findById(2L);
		verify(allocationItemMapper, never()).update(org.mockito.ArgumentMatchers.any());
	}
}
