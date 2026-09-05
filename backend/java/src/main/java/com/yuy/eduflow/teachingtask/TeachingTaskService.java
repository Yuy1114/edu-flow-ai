package com.yuy.eduflow.teachingtask;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classgroup.ClassGroupService;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomService;
import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.Assert;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.course.CourseService;
import com.yuy.eduflow.enums.ActiveStatus;
import com.yuy.eduflow.teacher.TeacherService;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 教学任务服务类
 * 负责教学任务的增删改查以及与其他业务模块（课程、教师、教室、班级）的关联逻辑
 */
@Service
public class TeachingTaskService {
    
    

    private final TeachingTaskMapper teachingTaskMapper;
    private final CourseService courseService;
    private final TeacherService teacherService;
    private final ClassGroupService classGroupService;
    private final ClassroomService classroomService;
    private final FormalScheduleMutationGuard formalScheduleMutationGuard;

    public TeachingTaskService(
            TeachingTaskMapper teachingTaskMapper,
            CourseService courseService,
            TeacherService teacherService,
            ClassGroupService classGroupService,
            ClassroomService classroomService,
            FormalScheduleMutationGuard formalScheduleMutationGuard) {
        this.teachingTaskMapper = teachingTaskMapper;
        this.courseService = courseService;
        this.teacherService = teacherService;
        this.classGroupService = classGroupService;
        this.classroomService = classroomService;
        this.formalScheduleMutationGuard = formalScheduleMutationGuard;
    }

    /**
     * 多条件查询教学任务
     * 
     * @param status     任务状态
     * @param courseId   课程ID
     * @param teacherId  教师ID
     * @param courseType 课程类型（理论课/上机课/实验课/实践课）
     * @param keyword    关键词（模糊搜索课程名、教师名、班级名）
     * @return 教学任务列表
     */
    public List<TeachingTask> findAll(String status, Long courseId, Long teacherId,
                                      String courseType, String taskBatch, String keyword) {
        return teachingTaskMapper.findAll(status, courseId, teacherId, courseType, taskBatch, keyword);
    }

    public Map<String, Object> findAllPaged(String status, Long courseId, Long teacherId,
                                            String courseType, String taskBatch, String keyword, int page, int size) {
        int offset = page * size;
        List<TeachingTask> content = teachingTaskMapper.findAllPaged(status, courseId, teacherId, courseType, taskBatch, keyword, size, offset);
        long total = teachingTaskMapper.findAllCount(status, courseId, teacherId, courseType, taskBatch, keyword);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("content", content);
        result.put("total", total);
        result.put("page", page);
        result.put("size", size);
        return result;
    }

    /**
     * 根据ID获取教学任务详情（包含关联的班级和教室信息）
     * 
     * @throws ResourceNotFoundException 当任务不存在时抛出
     */
    public TeachingTask findById(Long id) {
        TeachingTask task = teachingTaskMapper.findWithDetails(id);
        if (task == null) {
            throw new ResourceNotFoundException("教学任务不存在");
        }
        return task;
    }

    /**
     * 创建新的教学任务
     * 包含：基础信息保存、班级绑定
     * 
     * @param request 任务请求载体
     * @return 保存后的任务对象
     */
    @Transactional
    public TeachingTask create(TeachingTaskRequest request) {
        validateRequest(request);
        TeachingTask task = toTask(new TeachingTask(), request);
        teachingTaskMapper.insert(task);

        // 处理班级关联
        bindClassGroups(task.getId(), request.classGroupIds());
        bindCandidateClassrooms(task.getId(), request.candidateClassroomIds());

        return findById(task.getId());
    }

    /**
     * 更新教学任务
     * 逻辑：更新主表信息，并采用“先删后插”策略更新关联关系
     */
    @Transactional
    public TeachingTask update(Long id, TeachingTaskRequest request) {
        TeachingTask existing = findById(id); // 检查是否存在
        formalScheduleMutationGuard.lockAndRejectTeachingTask(id);
        validateRequest(request);

        TeachingTask task = toTask(existing, request);
        teachingTaskMapper.update(task);

        // 重置并重新绑定班级关联
        teachingTaskMapper.deleteClassGroups(id);
        bindClassGroups(id, request.classGroupIds());
        teachingTaskMapper.deleteClassrooms(id);
        bindCandidateClassrooms(id, request.candidateClassroomIds());

        return findById(id);
    }

    /**
     * 删除教学任务及其所有关联关系
     */
    @Transactional
    public void delete(Long id) {
        findById(id);
        formalScheduleMutationGuard.lockAndRejectTeachingTask(id);
        teachingTaskMapper.deleteClassGroups(id);
        teachingTaskMapper.deleteClassrooms(id);
        teachingTaskMapper.delete(id);
    }

    /**
     * 绑定教学任务与班级的多对多关系
     */
    private void bindClassGroups(Long taskId, List<Long> classGroupIds) {
        if (classGroupIds == null || classGroupIds.isEmpty()) {
            return;
        }
        for (Long classGroupId : classGroupIds) {
            if (classGroupId != null && classGroupId > 0) {
                teachingTaskMapper.insertClassGroup(taskId, classGroupId);
            }
        }
    }

    /** 候选教室为空表示由引擎从全部可用教室中选择；固定教室与候选集合互斥。 */
    private void bindCandidateClassrooms(Long taskId, List<Long> classroomIds) {
        if (classroomIds == null || classroomIds.isEmpty()) {
            return;
        }
        for (Long classroomId : classroomIds.stream().filter(java.util.Objects::nonNull).distinct().toList()) {
            if (classroomId > 0) {
                teachingTaskMapper.insertClassroom(taskId, classroomId);
            }
        }
    }

    /**
     * 将 DTO 请求数据映射到实体类
     */
    private TeachingTask toTask(TeachingTask task, TeachingTaskRequest request) {
        task.setCourseId(request.courseId());
        task.setPrimaryTeacherId(request.primaryTeacherId());
        task.setAssistantTeacherId(request.assistantTeacherId());
        task.setClassroomId(request.classroomId());
        task.setTotalHours(request.totalHours());
        task.setSessionsPerWeek(request.sessionsPerWeek());
        task.setDurationWeeks(request.durationWeeks());
        task.setRequiredRoomType(
                request.requiredRoomType() != null && !request.requiredRoomType().isBlank()
                        ? request.requiredRoomType().trim()
                        : null);
        task.setTaskBatch(request.taskBatch() != null && !request.taskBatch().isBlank() ? request.taskBatch().trim() : "DEFAULT");
        task.setNotes(request.notes());
        // 如果请求中未指定状态，则默认设置为 ACTIVE
        task.setStatus(
                request.status() != null && !request.status().isBlank() ? ActiveStatus.from(request.status().trim()) : ActiveStatus.ACTIVE);
        return task;
    }

    /**
     * 业务校验逻辑
     * 包含：非空校验、MVP 业务规则校验（2课时块、班级数量限制）、外部引用合法性检查
     */
    private void validateRequest(TeachingTaskRequest request) {
        Assert.positiveId(request.courseId(), "课程ID");
        Assert.positiveId(request.primaryTeacherId(), "主讲教师ID");

        // 自动排课仍使用课程默认的2/4节块；奇数尾差由终审课时审计暴露，
        // 必要时允许人工补一个45分钟原子节次。
        if (request.totalHours() == null || request.totalHours() <= 0) {
            throw new ValidationException("总课时必须大于0");
        }

        // 班级校验：合班上课不限班级数，冲突/教室容量由排课引擎按整体任务约束
        if (request.classGroupIds() == null || request.classGroupIds().isEmpty()) {
            throw new ValidationException("班级不能为空，至少需要关联1个班级");
        }
        if (request.classroomId() != null
                && request.candidateClassroomIds() != null
                && !request.candidateClassroomIds().isEmpty()) {
            throw new ValidationException("固定教室与候选教室不能同时设置");
        }

        // 级联校验：通过各模块 Service 检查 ID 是否在数据库中真实存在
        Course course = courseService.findById(request.courseId());
        teacherService.findById(request.primaryTeacherId());
		int sessionHours = TeachingSessionTimePolicy.periodCount(course.getCourseType());
		if (sessionHours == 0) {
			throw new ValidationException("课程类型缺失或不支持，无法确定一次课占用2节还是4节");
		}

        // 课时排布校验（可选字段，填了就必须自洽）:
        // 每周次数 × 持续周数 × 每次课时 == 总课时（理论/实践每次2课时，上机/实验连堂4课时）
        Integer sessions = request.sessionsPerWeek();
        Integer weeks = request.durationWeeks();
        if ((sessions == null) != (weeks == null)) {
            throw new ValidationException("课时排布需同时填写每周次数和持续周数，或都不填由系统推算");
        }
        if (sessions != null) {
            if (sessions <= 0 || weeks <= 0) {
                throw new ValidationException("每周次数和持续周数必须大于0");
            }
            int expected = sessions * weeks * sessionHours;
            if (expected != request.totalHours()) {
                throw new ValidationException(String.format(
                    "课时排布不自洽：每周%d次 × %d周 × 每次%d课时 = %d，与总课时 %d 不符",
                    sessions, weeks, sessionHours, expected, request.totalHours()));
            }
        }

        // 教室容量校验（仅当绑定了固定教室时）
        if (request.classroomId() != null) {
            Classroom classroom = classroomService.findById(request.classroomId());
            int totalStudents = 0;
            for (Long classGroupId : request.classGroupIds()) {
                ClassGroup classGroup = classGroupService.findById(classGroupId);
                if (classGroup.getStudentCount() != null) {
                    totalStudents += classGroup.getStudentCount();
                }
            }
            if (classroom.getCapacity() != null && totalStudents > classroom.getCapacity()) {
                throw new ValidationException(
                    "教室容量不足：教室「" + classroom.getName() + "」最多容纳 " + classroom.getCapacity() + " 人，"
                    + "但所选班级合计 " + totalStudents + " 人"
                );
            }
        }

        if (request.candidateClassroomIds() != null) {
            for (Long classroomId : request.candidateClassroomIds().stream()
                    .filter(java.util.Objects::nonNull).distinct().toList()) {
                Assert.positiveId(classroomId, "候选教室ID");
                classroomService.findById(classroomId);
            }
        }

        // 协作教师校验
        if (request.assistantTeacherId() != null && request.assistantTeacherId() > 0) {
            if (request.assistantTeacherId().equals(request.primaryTeacherId())) {
                throw new ValidationException("协作教师不能与主讲教师相同");
            }
            teacherService.findById(request.assistantTeacherId());
        }

        // 班级校验（主要是检查存在性，人数已在上方汇总）
        for (Long classGroupId : request.classGroupIds()) {
            classGroupService.findById(classGroupId);
        }
    }
}
