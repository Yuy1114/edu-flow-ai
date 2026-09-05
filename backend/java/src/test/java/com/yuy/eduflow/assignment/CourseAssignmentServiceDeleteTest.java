package com.yuy.eduflow.assignment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.enums.AssignmentStatus;
import com.yuy.eduflow.teacher.TeacherMapper;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.ObjectMapper;

@ExtendWith(MockitoExtension.class)
class CourseAssignmentServiceDeleteTest {
	@Mock private CourseAssignmentMapper mapper;
	@Mock private TeachingTaskMapper teachingTaskMapper;
	@Mock private TimeSlotService timeSlotService;
	@Mock private ClassroomMapper classroomMapper;
	@Mock private TeacherMapper teacherMapper;
	@Mock private TeacherProfileMapper teacherProfileMapper;
	@Mock private ObjectMapper objectMapper;
	@InjectMocks private CourseAssignmentService service;

	@Test
	void deleteMarksTheFormalAssignmentInactive() {
		CourseAssignment assignment = new CourseAssignment();
		assignment.setId(9L);
		assignment.setTeachingTaskId(10L);
		assignment.setStatus(AssignmentStatus.ACTIVE);
		when(mapper.findById(9L)).thenReturn(assignment);
		when(mapper.cancel(9L, AssignmentStatus.INACTIVE.code())).thenReturn(1);
		CourseAssignmentTaskHourAudit under = new CourseAssignmentTaskHourAudit();
		under.setTeachingTaskId(10L);
		under.setRequiredHours(3);
		under.setScheduledHours(0);
		under.setDeltaHours(-3);
		under.setStatus("UNDER");
		when(mapper.findHourAudit(null, 10L)).thenReturn(List.of(under));
		when(mapper.findHourAudit(null, null)).thenReturn(List.of(under));

		CourseAssignmentMutationResult mutation = service.delete(9L);
		CourseAssignmentHourAuditResult refreshed = service.findHourAudit(null, null);

		verify(mapper).cancel(9L, AssignmentStatus.INACTIVE.code());
		assertEquals("UNDER", mutation.hourAudit().tasks().get(0).getStatus());
		assertEquals(10L, refreshed.tasks().get(0).getTeachingTaskId());
		assertEquals(0, refreshed.scheduledTotalHours());
	}
}
