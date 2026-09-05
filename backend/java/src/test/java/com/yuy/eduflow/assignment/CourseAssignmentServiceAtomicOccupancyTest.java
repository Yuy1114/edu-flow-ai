package com.yuy.eduflow.assignment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.enums.ActiveStatus;
import com.yuy.eduflow.enums.AssignmentStatus;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.teacher.TeacherMapper;
import com.yuy.eduflow.teacher.TeacherProfile;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.apache.ibatis.annotations.Select;
import tools.jackson.databind.ObjectMapper;

@ExtendWith(MockitoExtension.class)
class CourseAssignmentServiceAtomicOccupancyTest {

	@Mock
	private CourseAssignmentMapper courseAssignmentMapper;
	@Mock
	private TeachingTaskMapper teachingTaskMapper;
	@Mock
	private TimeSlotService timeSlotService;
	@Mock
	private ClassroomMapper classroomMapper;
	@Mock
	private TeacherMapper teacherMapper;
	@Mock
	private TeacherProfileMapper teacherProfileMapper;

	private CourseAssignmentService service;
	private final ObjectMapper objectMapper = new ObjectMapper();

	@BeforeEach
	void setUp() {
		service = new CourseAssignmentService(
			courseAssignmentMapper,
			teachingTaskMapper,
			timeSlotService,
			classroomMapper,
			teacherMapper,
			teacherProfileMapper,
			objectMapper
		);
	}

	@Test
	void checksTheWholeTwoPeriodRangeInsteadOfOnlyTheStartSlot() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));
		when(courseAssignmentMapper.countActiveTeacherTimeConflict(42L, 30L, 2, 1, 3, 4)).thenReturn(1);

		ConflictException exception = assertThrows(
			ConflictException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("目标连续节次内教师已有其他课程安排", exception.getMessage());
		verify(courseAssignmentMapper, never()).updateSchedule(42L, 300L, 20L);
	}

	@Test
	void rejectsALabBlockThatWouldCrossASessionBoundary() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "上机课", 30L, null, List.of());
		when(timeSlotService.findById(700L)).thenReturn(slot(700L, 1, 6, 7));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 700L, 20L)
		);

		assertEquals("上机课一次课占连续4节，起始节次只能是1或5，不能跨上午、下午或晚间边界", exception.getMessage());
		verify(courseAssignmentMapper, never()).updateSchedule(42L, 700L, 20L);
	}

	@Test
	void permitsAnAlignedEveningTheoryBlockAndKeepsTheCurrentRoomWhenOmitted() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, 31L, List.of(classGroup(40L), classGroup(41L)));
		stubActiveResources(20L, 120, "普通教室", 30L, 31L);
		when(timeSlotService.findById(900L)).thenReturn(slot(900L, 4, 7, 9));
		when(courseAssignmentMapper.updateSchedule(42L, 900L, 20L)).thenReturn(1);

		service.moveAndRecheck(42L, 900L, null);

		verify(courseAssignmentMapper).countActiveTeacherTimeConflict(42L, 30L, 4, 7, 9, 10);
		verify(courseAssignmentMapper).countActiveTeacherTimeConflict(42L, 31L, 4, 7, 9, 10);
		verify(courseAssignmentMapper).countActiveClassGroupTimeConflict(42L, 40L, 4, 7, 9, 10);
		verify(courseAssignmentMapper).countActiveClassGroupTimeConflict(42L, 41L, 4, 7, 9, 10);
		verify(courseAssignmentMapper).countActiveClassroomTimeConflict(42L, 20L, 4, 7, 9, 10);
		verify(courseAssignmentMapper).updateSchedule(42L, 900L, 20L);
	}

	@Test
	void preservesAnExplicitOnePeriodManualCorrectionAtTheLastEveningSlot() {
		stubAssignment(42L, 10L, 20L, 1);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(901L)).thenReturn(slot(901L, 4, 7, 10));
		when(courseAssignmentMapper.updateSchedule(42L, 901L, 20L)).thenReturn(1);

		service.moveAndRecheck(42L, 901L, null);

		verify(courseAssignmentMapper).countActiveTeacherTimeConflict(42L, 30L, 4, 7, 10, 10);
		verify(courseAssignmentMapper).countActiveClassGroupTimeConflict(42L, 40L, 4, 7, 10, 10);
		verify(courseAssignmentMapper).countActiveClassroomTimeConflict(42L, 20L, 4, 7, 10, 10);
		verify(courseAssignmentMapper).updateSchedule(42L, 901L, 20L);
	}

	@Test
	void rejectsAnInactiveTeachingTask() {
		stubAssignment(42L, 10L, 20L);
		TeachingTask task = stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		task.setStatus(ActiveStatus.INACTIVE);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("教学任务不是启用状态，不能创建或调整正式课表", exception.getMessage());
		verify(courseAssignmentMapper, never()).updateSchedule(42L, 300L, 20L);
	}

	@Test
	void rejectsAnInactiveCourseAtTheFinalPublicationGate() {
		stubAssignment(42L, 10L, 20L);
		TeachingTask task = stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		task.getCourse().setStatus(ActiveStatus.INACTIVE);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("课程不是启用状态，不能创建或调整正式课表", exception.getMessage());
		verify(courseAssignmentMapper, never()).updateSchedule(42L, 300L, 20L);
	}

	@Test
	void rejectsAnInactiveClassroom() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubClassroom(20L, 120, "普通教室", ActiveStatus.INACTIVE);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("目标教室不是启用状态", exception.getMessage());
	}

	@Test
	void rejectsAnInactiveTeacher() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubClassroom(20L, 120, "普通教室", ActiveStatus.ACTIVE);
		stubTeacher(30L, ActiveStatus.INACTIVE);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("主讲教师不是启用状态", exception.getMessage());
	}

	@Test
	void enforcesTheTeachingTasksFixedClassroom() {
		stubAssignment(42L, 10L, 20L);
		TeachingTask task = stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		task.setClassroomId(21L);
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("教学任务已指定固定教室，不能改排到其他教室", exception.getMessage());
	}

	@Test
	void enforcesTheTeachingTasksCandidateClassrooms() {
		stubAssignment(42L, 10L, 20L);
		TeachingTask task = stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		Classroom candidate = new Classroom();
		candidate.setId(21L);
		task.setCandidateClassrooms(List.of(candidate));
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("目标教室不在教学任务的候选教室范围内", exception.getMessage());
	}

	@Test
	void rejectsAClassroomThatCannotHoldTheCombinedClass() {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubActiveResources(20L, 20, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("教室容量不足：教学任务班级共30人，目标教室容量20", exception.getMessage());
	}

	@Test
	void rejectsAClassroomWithTheWrongType() {
		stubAssignment(42L, 10L, 20L);
		TeachingTask task = stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		task.getCourse().setRequiredRoomType("计算机机房");
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("教室类型不匹配：教学任务需要机房，目标教室为普通教室", exception.getMessage());
	}

	@Test
	void rejectsAnyOccupiedAtomicPeriodThatIsHardUnavailableForTheTeacher() throws Exception {
		stubAssignment(42L, 10L, 20L);
		stubTask(10L, "理论课", 30L, null, List.of(classGroup(40L)));
		stubActiveResources(20L, 120, "普通教室", 30L);
		when(timeSlotService.findById(300L)).thenReturn(slot(300L, 2, 1, 3));
		List<List<Integer>> matrix = availabilityMatrix();
		matrix.get(3).set(0, -1);
		TeacherProfile profile = new TeacherProfile();
		profile.setTeacherId(30L);
		profile.setAvailabilityMatrixJson(objectMapper.writeValueAsString(matrix));
		when(teacherProfileMapper.findByTeacherId(30L)).thenReturn(profile);

		ValidationException exception = assertThrows(
			ValidationException.class,
			() -> service.moveAndRecheck(42L, 300L, 20L)
		);

		assertEquals("教师#30在周1第4节为硬禁排时间", exception.getMessage());
		verify(courseAssignmentMapper, never()).updateSchedule(42L, 300L, 20L);
	}

	@Test
	void exposesPerTaskAndGlobalAtomicHourConservation() {
		CourseAssignmentTaskHourAudit under = new CourseAssignmentTaskHourAudit();
		under.setTeachingTaskId(10L);
		under.setRequiredHours(3);
		under.setScheduledHours(2);
		under.setDeltaHours(-1);
		under.setStatus("UNDER");
		CourseAssignmentTaskHourAudit ok = new CourseAssignmentTaskHourAudit();
		ok.setTeachingTaskId(11L);
		ok.setRequiredHours(4);
		ok.setScheduledHours(4);
		ok.setDeltaHours(0);
		ok.setStatus("OK");
		when(courseAssignmentMapper.findHourAudit(null, null)).thenReturn(List.of(under, ok));

		CourseAssignmentHourAuditResult result = service.findHourAudit(null, null);

		assertEquals(7, result.requiredTotalHours());
		assertEquals(6, result.scheduledTotalHours());
		assertEquals(-1, result.deltaTotalHours());
		assertEquals(1, result.mismatchTaskCount());
	}

	@Test
	void manualCreateCannotInjectFormalLifecycleOrSourceSchemeState() {
		CourseAssignmentRequest injectedStatus = new CourseAssignmentRequest(null, 10L, 20L, 300L, 2, "INACTIVE");
		CourseAssignmentRequest injectedSource = new CourseAssignmentRequest(7L, 10L, 20L, 300L, 2, null);

		assertThrows(ValidationException.class, () -> service.create(injectedStatus));
		assertThrows(ValidationException.class, () -> service.create(injectedSource));

		verify(courseAssignmentMapper, never()).insert(org.mockito.ArgumentMatchers.any());
	}

	@Test
	void ordinaryUpdateCannotReassignTeachingTaskOrChangeThePublishedSpan() {
		stubAssignment(42L, 10L, 20L, 2);

		assertThrows(ValidationException.class, () -> service.update(
			42L, new CourseAssignmentRequest(null, 99L, 20L, 300L, 2, null)
		));
		assertThrows(ValidationException.class, () -> service.update(
			42L, new CourseAssignmentRequest(null, 10L, 20L, 300L, 4, null)
		));

		verify(courseAssignmentMapper, never()).update(org.mockito.ArgumentMatchers.any());
	}

	@Test
	void globalHourAuditSqlKeepsTasksWhoseLastActiveAssignmentWasDeleted() throws Exception {
		Select select = CourseAssignmentMapper.class
			.getMethod("findHourAudit", Long.class, Long.class)
			.getAnnotation(Select.class);
		String sql = String.join("\n", select.value());

		assertTrue(sql.contains("course_assignment historical_ca"));
		assertFalse(sql.contains("historical_ca.status"));
	}

	@Test
	void globalHourAuditSqlIncludesConfirmedTasksWithZeroMaterializedAssignments() throws Exception {
		Select select = CourseAssignmentMapper.class
			.getMethod("findHourAudit", Long.class, Long.class)
			.getAnnotation(Select.class);
		String sql = String.join("\n", select.value());

		assertTrue(sql.contains("allocation_task_teaching_task confirmed_att"));
		assertTrue(sql.contains("confirmed_scheme.status = 'CONFIRMED'"));
	}

	private void stubAssignment(Long id, Long taskId, Long classroomId) {
		stubAssignment(id, taskId, classroomId, null);
	}

	private void stubAssignment(Long id, Long taskId, Long classroomId, Integer consecutiveSlots) {
		CourseAssignment assignment = new CourseAssignment();
		assignment.setId(id);
		assignment.setTeachingTaskId(taskId);
		assignment.setClassroomId(classroomId);
		assignment.setConsecutiveSlots(consecutiveSlots);
		assignment.setStatus(AssignmentStatus.ACTIVE);
		when(courseAssignmentMapper.findById(id)).thenReturn(assignment);
	}

	private TeachingTask stubTask(
		Long id,
		String courseType,
		Long primaryTeacherId,
		Long assistantTeacherId,
		List<ClassGroup> classGroups
	) {
		Course course = new Course();
		course.setCourseType(courseType);
		course.setRequiredRoomType("普通教室");
		course.setStatus(ActiveStatus.ACTIVE);
		TeachingTask task = new TeachingTask();
		task.setId(id);
		task.setCourse(course);
		task.setStatus(ActiveStatus.ACTIVE);
		task.setPrimaryTeacherId(primaryTeacherId);
		task.setAssistantTeacherId(assistantTeacherId);
		task.setClassGroups(classGroups);
		when(teachingTaskMapper.findWithDetails(id)).thenReturn(task);
		return task;
	}

	private ClassGroup classGroup(Long id) {
		ClassGroup classGroup = new ClassGroup();
		classGroup.setId(id);
		classGroup.setStudentCount(30);
		return classGroup;
	}

	private void stubActiveResources(
		Long classroomId,
		int capacity,
		String classroomType,
		Long... teacherIds
	) {
		stubClassroom(classroomId, capacity, classroomType, ActiveStatus.ACTIVE);
		for (Long teacherId : teacherIds) {
			stubTeacher(teacherId, ActiveStatus.ACTIVE);
		}
	}

	private void stubClassroom(Long id, int capacity, String classroomType, ActiveStatus status) {
		Classroom classroom = new Classroom();
		classroom.setId(id);
		classroom.setCapacity(capacity);
		classroom.setClassroomType(classroomType);
		classroom.setStatus(status);
		when(classroomMapper.findById(id)).thenReturn(classroom);
	}

	private void stubTeacher(Long id, ActiveStatus status) {
		Teacher teacher = new Teacher();
		teacher.setId(id);
		teacher.setStatus(status);
		when(teacherMapper.findById(id)).thenReturn(teacher);
	}

	private List<List<Integer>> availabilityMatrix() {
		List<List<Integer>> matrix = new ArrayList<>();
		for (int period = 0; period < 10; period++) {
			matrix.add(new ArrayList<>(List.of(0, 0, 0, 0, 0, 0, 0)));
		}
		return matrix;
	}

	private TimeSlot slot(Long id, int week, int day, int period) {
		TimeSlot slot = new TimeSlot();
		slot.setId(id);
		slot.setWeekNumber(week);
		slot.setDayOfWeek(day);
		slot.setPeriodIndex(period);
		return slot;
	}
}
