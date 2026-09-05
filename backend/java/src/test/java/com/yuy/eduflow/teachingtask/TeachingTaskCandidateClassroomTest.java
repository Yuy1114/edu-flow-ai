package com.yuy.eduflow.teachingtask;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classgroup.ClassGroupService;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomService;
import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.course.CourseService;
import com.yuy.eduflow.teacher.TeacherService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.ArgumentCaptor;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class TeachingTaskCandidateClassroomTest {

	@Mock TeachingTaskMapper mapper;
	@Mock CourseService courseService;
	@Mock TeacherService teacherService;
	@Mock ClassGroupService classGroupService;
	@Mock ClassroomService classroomService;
	@Mock FormalScheduleMutationGuard formalScheduleMutationGuard;

	private TeachingTaskService service;

	@BeforeEach
	void setUp() {
		service = new TeachingTaskService(
			mapper, courseService, teacherService, classGroupService, classroomService, formalScheduleMutationGuard
		);
	}

	@Test
	void candidateClassroomsArePersistedAsAStableSet() {
		Course course = new Course();
		course.setCourseType("理论课");
		when(courseService.findById(1L)).thenReturn(course);
		ClassGroup classGroup = new ClassGroup();
		classGroup.setStudentCount(40);
		when(classGroupService.findById(4L)).thenReturn(classGroup);
		when(classroomService.findById(8L)).thenReturn(new Classroom());
		when(classroomService.findById(9L)).thenReturn(new Classroom());
		when(mapper.insert(any(TeachingTask.class))).thenAnswer(invocation -> {
			invocation.<TeachingTask>getArgument(0).setId(42L);
			return 1;
		});
		TeachingTask saved = new TeachingTask();
		saved.setId(42L);
		when(mapper.findWithDetails(42L)).thenReturn(saved);

		service.create(request(null, List.of(8L, 9L, 8L)));

		verify(mapper).insertClassroom(42L, 8L);
		verify(mapper).insertClassroom(42L, 9L);
	}

	@Test
	void fixedAndCandidateClassroomsCannotBeCombined() {
		assertThrows(
			ValidationException.class,
			() -> service.create(request(8L, List.of(9L)))
		);
		verify(mapper, never()).insert(any(TeachingTask.class));
	}

	@Test
	void oddTotalHoursCanBeAuditedAndCompletedWithOneManualAtomicPeriod() {
		Course course = new Course();
		course.setCourseType("理论课");
		when(courseService.findById(1L)).thenReturn(course);
		ClassGroup classGroup = new ClassGroup();
		classGroup.setStudentCount(40);
		when(classGroupService.findById(4L)).thenReturn(classGroup);
		when(mapper.insert(any(TeachingTask.class))).thenAnswer(invocation -> {
			invocation.<TeachingTask>getArgument(0).setId(43L);
			return 1;
		});
		TeachingTask saved = new TeachingTask();
		saved.setId(43L);
		when(mapper.findWithDetails(43L)).thenReturn(saved);
		TeachingTaskRequest request = new TeachingTaskRequest(
			1L, 2L, null, null,
			31, null, null, "普通教室", "TEST", null, "ACTIVE",
			List.of(4L), List.of()
		);

		service.create(request);

		ArgumentCaptor<TeachingTask> taskCaptor = ArgumentCaptor.forClass(TeachingTask.class);
		verify(mapper).insert(taskCaptor.capture());
		assertEquals(31, taskCaptor.getValue().getTotalHours());
	}

	private TeachingTaskRequest request(Long fixedClassroomId, List<Long> candidates) {
		return new TeachingTaskRequest(
			1L, 2L, null, fixedClassroomId,
			32, 2, 8, "普通教室", "TEST", null, "ACTIVE",
			List.of(4L), candidates
		);
	}
}
