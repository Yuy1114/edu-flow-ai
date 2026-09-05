package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AllocationSchemeConflictDetectorAtomicOccupancyTest {

	@Mock
	private AllocationItemMapper allocationItemMapper;
	@Mock
	private AllocationTaskMapper allocationTaskMapper;
	@Mock
	private TeachingTaskMapper teachingTaskMapper;
	@Mock
	private ClassroomMapper classroomMapper;
	@Mock
	private TimeSlotService timeSlotService;

	private AllocationSchemeConflictDetector detector;

	@BeforeEach
	void setUp() {
		detector = new AllocationSchemeConflictDetector(
			allocationItemMapper,
			allocationTaskMapper,
			teachingTaskMapper,
			classroomMapper,
			timeSlotService
		);
		when(timeSlotService.findAll(null, null)).thenReturn(daySlots(1, 1));
	}

	@Test
	void catchesOverlapBetweenALabStartingAtOneAndTheoryStartingAtThree() {
		ClassGroup sharedClass = classGroup(50L, "软件工程1班");
		TeachingTask lab = task(10L, "上机课", 4, 30L, sharedClass);
		TeachingTask theory = task(11L, "理论课", 2, 30L, sharedClass);
		when(teachingTaskMapper.findWithDetails(10L)).thenReturn(lab);
		when(teachingTaskMapper.findWithDetails(11L)).thenReturn(theory);
		when(classroomMapper.findById(100L)).thenReturn(classroom(100L));

		List<AllocationConflictViolation> violations = detector.detect(List.of(
			item(1L, 10L, 100L, slotId(1)),
			item(2L, 11L, 100L, slotId(3))
		));

		assertEquals(2, count(violations, AllocationSchemeConflictDetector.TEACHER_TIME));
		assertEquals(2, count(violations, AllocationSchemeConflictDetector.CLASS_GROUP_TIME));
		assertEquals(2, count(violations, AllocationSchemeConflictDetector.CLASSROOM_TIME));
		assertEquals(0, count(violations, AllocationSchemeConflictDetector.TEACHING_TASK_HOURS));
		assertFalse(violations.stream()
			.filter(v -> AllocationSchemeConflictDetector.TEACHER_TIME.equals(v.conflictType()))
			.anyMatch(v -> !Long.valueOf(slotId(3)).equals(v.relatedTimeSlotId())));
	}

	@Test
	void reportsAnIllegalCrossBoundaryStartAsAnExplicitViolation() {
		TeachingTask theory = task(10L, "理论课", 2, 30L, classGroup(50L, "软件工程1班"));
		when(teachingTaskMapper.findWithDetails(10L)).thenReturn(theory);
		when(classroomMapper.findById(100L)).thenReturn(classroom(100L));

		List<AllocationConflictViolation> violations = detector.detect(List.of(
			item(1L, 10L, 100L, slotId(4))
		));

		assertEquals(1, count(violations, AllocationSchemeConflictDetector.INVALID_TIME_BLOCK));
	}

	private long count(List<AllocationConflictViolation> violations, String type) {
		return violations.stream().filter(v -> type.equals(v.conflictType())).count();
	}

	private TeachingTask task(Long id, String courseType, int totalHours, Long teacherId, ClassGroup classGroup) {
		Course course = new Course();
		course.setName("课程" + id);
		course.setCourseType(courseType);
		TeachingTask task = new TeachingTask();
		task.setId(id);
		task.setCourse(course);
		task.setPrimaryTeacherId(teacherId);
		task.setTotalHours(totalHours);
		task.setClassGroups(List.of(classGroup));
		return task;
	}

	private ClassGroup classGroup(Long id, String name) {
		ClassGroup classGroup = new ClassGroup();
		classGroup.setId(id);
		classGroup.setName(name);
		classGroup.setStudentCount(30);
		return classGroup;
	}

	private Classroom classroom(Long id) {
		Classroom classroom = new Classroom();
		classroom.setId(id);
		classroom.setName("A101");
		classroom.setCapacity(100);
		return classroom;
	}

	private AllocationItem item(Long id, Long taskId, Long classroomId, Long timeSlotId) {
		AllocationItem item = new AllocationItem();
		item.setId(id);
		item.setTeachingTaskId(taskId);
		item.setClassroomId(classroomId);
		item.setTimeSlotId(timeSlotId);
		return item;
	}

	private List<TimeSlot> daySlots(int week, int day) {
		return java.util.stream.IntStream.rangeClosed(1, 10)
			.mapToObj(period -> {
				TimeSlot slot = new TimeSlot();
				slot.setId(slotId(period));
				slot.setWeekNumber(week);
				slot.setDayOfWeek(day);
				slot.setPeriodIndex(period);
				return slot;
			})
			.toList();
	}

	private long slotId(int period) {
		return 1000L + period;
	}
}
