package com.yuy.eduflow.assignment;

import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.common.Assert;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.ActiveStatus;
import com.yuy.eduflow.enums.AssignmentStatus;
import com.yuy.eduflow.teacher.AvailabilityMatrixPolicy;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.teacher.TeacherMapper;
import com.yuy.eduflow.teacher.TeacherProfile;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

@Service
public class CourseAssignmentService {
	

	private final CourseAssignmentMapper courseAssignmentMapper;
	private final TeachingTaskMapper teachingTaskMapper;
	private final TimeSlotService timeSlotService;
	private final ClassroomMapper classroomMapper;
	private final TeacherMapper teacherMapper;
	private final TeacherProfileMapper teacherProfileMapper;
	private final ObjectMapper objectMapper;

	public CourseAssignmentService(
		CourseAssignmentMapper courseAssignmentMapper,
		TeachingTaskMapper teachingTaskMapper,
		TimeSlotService timeSlotService,
		ClassroomMapper classroomMapper,
		TeacherMapper teacherMapper,
		TeacherProfileMapper teacherProfileMapper,
		ObjectMapper objectMapper
	) {
		this.courseAssignmentMapper = courseAssignmentMapper;
		this.teachingTaskMapper = teachingTaskMapper;
		this.timeSlotService = timeSlotService;
		this.classroomMapper = classroomMapper;
		this.teacherMapper = teacherMapper;
		this.teacherProfileMapper = teacherProfileMapper;
		this.objectMapper = objectMapper;
	}

	public List<CourseAssignment> findAll(
		Long teacherId,
		Long classGroupId,
		Long courseId,
		Long classroomId,
		String status,
		Integer weekNumber
	) {
		validateOptionalId(teacherId, "教师ID必须大于0");
		validateOptionalId(classGroupId, "班级ID必须大于0");
		validateOptionalId(courseId, "课程ID必须大于0");
		validateOptionalId(classroomId, "教室ID必须大于0");
		validateOptionalWeekNumber(weekNumber);
		return courseAssignmentMapper.findAll(teacherId, classGroupId, courseId, classroomId, normalizeStatus(status), weekNumber);
	}

	public List<CourseAssignmentView> findViews(
		Long teacherId,
		Long classGroupId,
		Long courseId,
		Long classroomId,
		Integer weekNumber,
		Integer dayOfWeek,
		String status
	) {
		validateOptionalId(teacherId, "教师ID必须大于0");
		validateOptionalId(classGroupId, "班级ID必须大于0");
		validateOptionalId(courseId, "课程ID必须大于0");
		validateOptionalId(classroomId, "教室ID必须大于0");
		validateOptionalWeekNumber(weekNumber);
		validateOptionalDayOfWeek(dayOfWeek);
		return courseAssignmentMapper.findViews(
			teacherId,
			classGroupId,
			courseId,
			classroomId,
			weekNumber,
			dayOfWeek,
			normalizeStatus(status)
		);
	}

	public List<CourseAssignmentView> findTeacherAssignments(Long teacherId, Integer weekNumber, Integer dayOfWeek) {
		Assert.positiveId(teacherId, "教师ID");
		return findViews(teacherId, null, null, null, weekNumber, dayOfWeek, null);
	}

	public List<CourseAssignmentView> findClassGroupAssignments(Long classGroupId, Integer weekNumber, Integer dayOfWeek) {
		Assert.positiveId(classGroupId, "班级ID");
		return findViews(null, classGroupId, null, null, weekNumber, dayOfWeek, null);
	}

	public CourseAssignment findById(Long id) {
		CourseAssignment assignment = courseAssignmentMapper.findById(id);
		if (assignment == null) {
			throw new ResourceNotFoundException("课程安排不存在");
		}
		return assignment;
	}

	@Transactional
	public CourseAssignmentMutationResult create(CourseAssignmentRequest request) {
		courseAssignmentMapper.lockSchedulePublication();
		CourseAssignment assignment = toNewManualAssignment(request);
		validateScheduleAndConflicts(null, assignment.getTeachingTaskId(), assignment.getClassroomId(), assignment.getTimeSlotId(), assignment.getConsecutiveSlots());
		courseAssignmentMapper.insert(assignment);
		CourseAssignment saved = findById(assignment.getId());
		return new CourseAssignmentMutationResult(saved, findHourAudit(null, saved.getTeachingTaskId()));
	}

	@Transactional
	public CourseAssignmentMutationResult update(Long id, CourseAssignmentRequest request) {
		courseAssignmentMapper.lockSchedulePublication();
		CourseAssignment existing = findById(id);
		requireActive(existing);
		CourseAssignment assignment = toManualScheduleUpdate(existing, request);
		validateScheduleAndConflicts(id, assignment.getTeachingTaskId(), assignment.getClassroomId(), assignment.getTimeSlotId(), assignment.getConsecutiveSlots());
		if (courseAssignmentMapper.update(assignment) != 1) {
			throw new ConflictException("正式课表状态已变化，修改未保存");
		}
		CourseAssignment saved = findById(id);
		return new CourseAssignmentMutationResult(saved, findHourAudit(null, saved.getTeachingTaskId()));
	}

	@Transactional
	public CourseAssignmentMutationResult delete(Long id) {
		courseAssignmentMapper.lockSchedulePublication();
		CourseAssignment assignment = findById(id);
		requireActive(assignment);
		if (courseAssignmentMapper.cancel(id, AssignmentStatus.INACTIVE.code()) != 1) {
			throw new ConflictException("正式课表状态已变化，删除未保存");
		}
		assignment.setStatus(AssignmentStatus.INACTIVE);
		return new CourseAssignmentMutationResult(
			assignment,
			findHourAudit(null, assignment.getTeachingTaskId())
		);
	}

	@Transactional
	public CourseAssignmentMutationResult moveAndRecheck(Long id, Long timeSlotId, Long classroomId) {
		courseAssignmentMapper.lockSchedulePublication();
		CourseAssignment assignment = findById(id);
		requireActive(assignment);
		Assert.positiveId(timeSlotId, "时间段ID");
		Long targetClassroomId = classroomId != null ? classroomId : assignment.getClassroomId();
		Assert.positiveId(targetClassroomId, "教室ID");
		validateScheduleAndConflicts(id, assignment.getTeachingTaskId(), targetClassroomId, timeSlotId, assignment.getConsecutiveSlots());
		if (courseAssignmentMapper.updateSchedule(id, timeSlotId, targetClassroomId) != 1) {
			throw new ConflictException("正式课表状态已变化，移动未保存");
		}
		CourseAssignment moved = findById(id);
		return new CourseAssignmentMutationResult(moved, findHourAudit(null, moved.getTeachingTaskId()));
	}

	public CourseAssignmentHourAuditResult findHourAudit(Long allocationTaskId, Long teachingTaskId) {
		validateOptionalId(allocationTaskId, "排课任务ID必须大于0");
		validateOptionalId(teachingTaskId, "教学任务ID必须大于0");
		List<CourseAssignmentTaskHourAudit> tasks = courseAssignmentMapper.findHourAudit(allocationTaskId, teachingTaskId);
		int required = tasks.stream().mapToInt(row -> Objects.requireNonNullElse(row.getRequiredHours(), 0)).sum();
		int scheduled = tasks.stream().mapToInt(row -> Objects.requireNonNullElse(row.getScheduledHours(), 0)).sum();
		int mismatches = (int) tasks.stream().filter(row -> !"OK".equals(row.getStatus())).count();
		return new CourseAssignmentHourAuditResult(required, scheduled, scheduled - required, mismatches, List.copyOf(tasks));
	}

	/** Final publication gate used immediately before inserting a formal assignment. */
	public void validateForPublication(CourseAssignment assignment) {
		if (assignment == null) throw new ValidationException("待发布的正式课表安排不能为空");
		Assert.positiveId(assignment.getTeachingTaskId(), "教学任务ID");
		Assert.positiveId(assignment.getClassroomId(), "教室ID");
		Assert.positiveId(assignment.getTimeSlotId(), "时间段ID");
		validateScheduleAndConflicts(
			null,
			assignment.getTeachingTaskId(),
			assignment.getClassroomId(),
			assignment.getTimeSlotId(),
			assignment.getConsecutiveSlots()
		);
	}

	private void validateScheduleAndConflicts(
		Long excludedAssignmentId,
		Long teachingTaskId,
		Long classroomId,
		Long timeSlotId,
		Integer requestedConsecutiveSlots
	) {
		TeachingTask task = teachingTaskMapper.findWithDetails(teachingTaskId);
		if (task == null) {
			throw new ResourceNotFoundException("教学任务不存在");
		}
		TimeSlot targetSlot = timeSlotService.findById(timeSlotId);
		String courseType = task.getCourse() == null ? null : task.getCourse().getCourseType();
		int defaultPeriodCount = TeachingSessionTimePolicy.periodCount(courseType);
		if (defaultPeriodCount == 0) {
			throw new ValidationException("教学任务课程类型缺失或不支持，无法确定一次课占用2节还是4节");
		}
		int periodCount = requestedConsecutiveSlots == null ? defaultPeriodCount : requestedConsecutiveSlots;
		if (periodCount != 1 && periodCount != defaultPeriodCount) {
			throw new ValidationException(courseType + "正式安排默认连续" + defaultPeriodCount + "节，人工仅可显式补1节");
		}
		int startPeriod = targetSlot.getPeriodIndex();
		if (periodCount > 1 && !TeachingSessionTimePolicy.isLegalStartPeriod(startPeriod, periodCount)) {
			throw new ValidationException(
				courseType + "一次课占连续" + periodCount + "节，起始节次只能是"
					+ TeachingSessionTimePolicy.legalStartDescription(periodCount)
					+ "，不能跨上午、下午或晚间边界"
			);
		}
		int endPeriod = startPeriod + periodCount - 1;
		validateHardConstraints(task, classroomId, targetSlot, startPeriod, endPeriod);
		long excludedId = excludedAssignmentId == null ? -1L : excludedAssignmentId;

		Set<Long> teacherIds = new LinkedHashSet<>();
		if (task.getPrimaryTeacherId() != null) teacherIds.add(task.getPrimaryTeacherId());
		if (task.getAssistantTeacherId() != null) teacherIds.add(task.getAssistantTeacherId());
		for (Long teacherId : teacherIds) {
			int conflicts = courseAssignmentMapper.countActiveTeacherTimeConflict(
				excludedId, teacherId, targetSlot.getWeekNumber(), targetSlot.getDayOfWeek(), startPeriod, endPeriod
			);
			if (conflicts > 0) {
				throw new ConflictException("目标连续节次内教师已有其他课程安排");
			}
		}

		if (task.getClassGroups() != null) {
			for (var classGroup : task.getClassGroups()) {
				if (classGroup.getId() == null) continue;
				int conflicts = courseAssignmentMapper.countActiveClassGroupTimeConflict(
					excludedId, classGroup.getId(), targetSlot.getWeekNumber(), targetSlot.getDayOfWeek(), startPeriod, endPeriod
				);
				if (conflicts > 0) {
					throw new ConflictException("目标连续节次内班级已有其他课程安排");
				}
			}
		}

		int classroomConflicts = courseAssignmentMapper.countActiveClassroomTimeConflict(
			excludedId, classroomId, targetSlot.getWeekNumber(), targetSlot.getDayOfWeek(), startPeriod, endPeriod
		);
		if (classroomConflicts > 0) {
			throw new ConflictException("目标连续节次内教室已被占用");
		}
	}

	private void validateHardConstraints(
		TeachingTask task,
		Long classroomId,
		TimeSlot targetSlot,
		int startPeriod,
		int endPeriod
	) {
		if (task.getStatus() != ActiveStatus.ACTIVE) {
			throw new ValidationException("教学任务不是启用状态，不能创建或调整正式课表");
		}
		if (task.getCourse() == null || task.getCourse().getStatus() != ActiveStatus.ACTIVE) {
			throw new ValidationException("课程不是启用状态，不能创建或调整正式课表");
		}

		Classroom classroom = classroomMapper.findById(classroomId);
		if (classroom == null) {
			throw new ResourceNotFoundException("目标教室不存在");
		}
		if (classroom.getStatus() != ActiveStatus.ACTIVE) {
			throw new ValidationException("目标教室不是启用状态");
		}

		Set<Long> teacherIds = new LinkedHashSet<>();
		validateActiveTeacher(task.getPrimaryTeacherId(), "主讲教师", teacherIds);
		if (task.getAssistantTeacherId() != null) {
			validateActiveTeacher(task.getAssistantTeacherId(), "协作教师", teacherIds);
		}

		if (task.getClassroomId() != null && !Objects.equals(task.getClassroomId(), classroomId)) {
			throw new ValidationException("教学任务已指定固定教室，不能改排到其他教室");
		}
		if (task.getClassroomId() == null
			&& task.getCandidateClassrooms() != null
			&& !task.getCandidateClassrooms().isEmpty()
			&& task.getCandidateClassrooms().stream()
				.noneMatch(candidate -> candidate != null && Objects.equals(candidate.getId(), classroomId))) {
			throw new ValidationException("目标教室不在教学任务的候选教室范围内");
		}

		if (task.getClassGroups() == null || task.getClassGroups().isEmpty()) {
			throw new ValidationException("教学任务未关联班级，不能创建正式课表");
		}
		Set<Long> classGroupIds = new LinkedHashSet<>();
		int totalStudents = 0;
		for (var classGroup : task.getClassGroups()) {
			if (classGroup == null || classGroup.getId() == null) {
				throw new ValidationException("教学任务包含无稳定ID的班级关系");
			}
			if (classGroupIds.add(classGroup.getId())) {
				totalStudents += Math.max(0, Objects.requireNonNullElse(classGroup.getStudentCount(), 0));
			}
		}
		if (classroom.getCapacity() == null || totalStudents > classroom.getCapacity()) {
			throw new ValidationException(
				"教室容量不足：教学任务班级共%d人，目标教室容量%s".formatted(
					totalStudents,
					classroom.getCapacity() == null ? "未配置" : classroom.getCapacity().toString()
				)
			);
		}

		String requiredRoomType = StringUtils.hasText(task.getRequiredRoomType())
			? task.getRequiredRoomType()
			: task.getCourse() == null ? null : task.getCourse().getRequiredRoomType();
		String normalizedRequiredType = normalizeRoomType(requiredRoomType);
		String normalizedActualType = normalizeRoomType(classroom.getClassroomType());
		if (StringUtils.hasText(normalizedRequiredType)
			&& !normalizedRequiredType.equals(normalizedActualType)) {
			throw new ValidationException(
				"教室类型不匹配：教学任务需要%s，目标教室为%s".formatted(
					normalizedRequiredType,
					StringUtils.hasText(normalizedActualType) ? normalizedActualType : "未标注"
				)
			);
		}

		for (Long teacherId : teacherIds) {
			TeacherProfile profile = teacherProfileMapper.findByTeacherId(teacherId);
			if (profile == null) continue;
			for (int period = startPeriod; period <= endPeriod; period++) {
				if (AvailabilityMatrixPolicy.isHardUnavailable(
					objectMapper,
					profile.getAvailabilityMatrixJson(),
					targetSlot.getDayOfWeek(),
					period
				)) {
					throw new ValidationException(
						"教师#%d在周%d第%d节为硬禁排时间".formatted(
							teacherId, targetSlot.getDayOfWeek(), period
						)
					);
				}
			}
		}
	}

	private void validateActiveTeacher(Long teacherId, String role, Set<Long> teacherIds) {
		if (teacherId == null || teacherId <= 0) {
			throw new ValidationException("教学任务缺少有效" + role + "ID");
		}
		Teacher teacher = teacherMapper.findById(teacherId);
		if (teacher == null) {
			throw new ResourceNotFoundException("教学任务引用的" + role + "不存在");
		}
		if (teacher.getStatus() != ActiveStatus.ACTIVE) {
			throw new ValidationException(role + "不是启用状态");
		}
		teacherIds.add(teacherId);
	}

	private String normalizeRoomType(String value) {
		if (!StringUtils.hasText(value)) return null;
		String normalized = value.trim();
		if (normalized.contains("机房") || normalized.contains("计算机")) return "机房";
		if (normalized.contains("普通") || normalized.contains("教室")) return "普通教室";
		return normalized;
	}

	private CourseAssignment toNewManualAssignment(CourseAssignmentRequest request) {
		if (request == null) throw new ValidationException("正式课表安排请求不能为空");
		if (request.sourceSchemeId() != null) {
			throw new ValidationException("人工新增正式课表不能指定来源方案；来源方案仅由确认发布流程写入");
		}
		if (StringUtils.hasText(request.status())) {
			throw new ValidationException("正式课表状态由服务端管理；新增固定为ACTIVE");
		}
		Assert.positiveId(request.teachingTaskId(), "教学任务ID");
		Assert.positiveId(request.classroomId(), "教室ID");
		Assert.positiveId(request.timeSlotId(), "时间段ID");
		CourseAssignment assignment = new CourseAssignment();
		assignment.setSourceSchemeId(null);
		assignment.setTeachingTaskId(request.teachingTaskId());
		assignment.setClassroomId(request.classroomId());
		assignment.setTimeSlotId(request.timeSlotId());
		TeachingTask task = teachingTaskMapper.findWithDetails(request.teachingTaskId());
		if (task == null || task.getCourse() == null) throw new ResourceNotFoundException("教学任务不存在");
		int defaultPeriods = TeachingSessionTimePolicy.periodCount(task.getCourse().getCourseType());
		assignment.setConsecutiveSlots(request.consecutiveSlots() == null ? defaultPeriods : request.consecutiveSlots());
		assignment.setStatus(AssignmentStatus.ACTIVE);
		return assignment;
	}

	private CourseAssignment toManualScheduleUpdate(CourseAssignment existing, CourseAssignmentRequest request) {
		if (request == null) throw new ValidationException("正式课表安排请求不能为空");
		if (request.sourceSchemeId() != null) {
			throw new ValidationException("来源方案不可通过普通修改接口覆盖");
		}
		if (StringUtils.hasText(request.status())) {
			throw new ValidationException("正式课表状态不可通过普通修改接口覆盖");
		}
		if (request.teachingTaskId() != null && !Objects.equals(request.teachingTaskId(), existing.getTeachingTaskId())) {
			throw new ValidationException("教学任务不可通过普通修改接口替换；请删除后由人工新增或重新发布");
		}
		if (request.consecutiveSlots() != null && !Objects.equals(request.consecutiveSlots(), existing.getConsecutiveSlots())) {
			throw new ValidationException("连续节数不可通过普通修改接口覆盖；请删除后按1/2/4节重新新增");
		}
		Assert.positiveId(request.classroomId(), "教室ID");
		Assert.positiveId(request.timeSlotId(), "时间段ID");
		CourseAssignment assignment = new CourseAssignment();
		assignment.setId(existing.getId());
		assignment.setSourceSchemeId(existing.getSourceSchemeId());
		assignment.setTeachingTaskId(existing.getTeachingTaskId());
		assignment.setClassroomId(request.classroomId());
		assignment.setTimeSlotId(request.timeSlotId());
		assignment.setConsecutiveSlots(existing.getConsecutiveSlots());
		assignment.setStatus(AssignmentStatus.ACTIVE);
		return assignment;
	}

	private void requireActive(CourseAssignment assignment) {
		if (assignment.getStatus() != AssignmentStatus.ACTIVE) {
			throw new ConflictException("只有ACTIVE正式课表安排可以修改、移动或删除");
		}
	}

	private void validateOptionalId(Long id, String message) {
		if (id != null && id <= 0) {
			throw new ValidationException(message);
		}
	}

	private void validateOptionalWeekNumber(Integer weekNumber) {
		if (weekNumber != null && (weekNumber < SchedulingTimePolicy.FIRST_WEEK
			|| weekNumber > SchedulingTimePolicy.LAST_WEEK)) {
			throw new ValidationException("周次必须在1到18之间");
		}
	}

	private void validateOptionalDayOfWeek(Integer dayOfWeek) {
		if (dayOfWeek != null && (dayOfWeek < 1 || dayOfWeek > 7)) {
			throw new ValidationException("星期必须在1到7之间");
		}
	}

	private String normalizeStatus(String status) {
		return StringUtils.hasText(status) ? status.trim() : AssignmentStatus.ACTIVE.code();
	}
}
