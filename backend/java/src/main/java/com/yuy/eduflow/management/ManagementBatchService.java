package com.yuy.eduflow.management;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.ActiveStatus;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ManagementBatchService {

    private static final Map<String, EntityTarget> TARGETS = Map.of(
            "teachers", new EntityTarget("teacher", true),
            "classrooms", new EntityTarget("classroom", true),
            "courses", new EntityTarget("course", true),
            "class-groups", new EntityTarget("class_group", false),
            "teaching-tasks", new EntityTarget("teaching_task", true)
    );

    private final ManagementBatchMapper mapper;
    private final FormalScheduleMutationGuard formalScheduleMutationGuard;

    public ManagementBatchService(
            ManagementBatchMapper mapper,
            FormalScheduleMutationGuard formalScheduleMutationGuard) {
        this.mapper = mapper;
        this.formalScheduleMutationGuard = formalScheduleMutationGuard;
    }

    @Transactional
    public int disable(String entity, List<Long> ids) {
        EntityTarget target = target(entity);
        if (!target.disableSupported()) {
            throw new ValidationException("该数据类型暂不支持禁用");
        }
        List<Long> normalizedIds = normalizeIds(ids);
        rejectPublishedReferences(target, normalizedIds);
        return mapper.updateStatus(target.tableName(), normalizedIds, ActiveStatus.INACTIVE.code());
    }

    @Transactional
    public int delete(String entity, List<Long> ids) {
        EntityTarget target = target(entity);
        List<Long> normalizedIds = normalizeIds(ids);
        rejectPublishedReferences(target, normalizedIds);
        rejectFormalHistoryDeletion(target, normalizedIds);
        if ("teaching_task".equals(target.tableName())) {
            deleteTeachingTaskDependencies(normalizedIds);
        }
        if ("course".equals(target.tableName())) {
            List<Long> teachingTaskIds = mapper.findTeachingTaskIdsByCourseIds(normalizedIds);
            if (!teachingTaskIds.isEmpty()) {
                deleteTeachingTasks(teachingTaskIds);
            }
        }
        if ("teacher".equals(target.tableName())) {
            List<Long> teachingTaskIds = mapper.findTeachingTaskIdsByTeacherIds(normalizedIds);
            if (!teachingTaskIds.isEmpty()) {
                deleteTeachingTasks(teachingTaskIds);
            }
            mapper.deleteTeacherProfiles(normalizedIds);
        }
        return mapper.deleteRows(target.tableName(), normalizedIds);
    }

    private void deleteTeachingTasks(List<Long> ids) {
        deleteTeachingTaskDependencies(ids);
        mapper.deleteRows("teaching_task", ids);
    }

    private void deleteTeachingTaskDependencies(List<Long> ids) {
        mapper.detachConflictCheckResults(ids);
        mapper.detachMlFeedbackEvents(ids);
        mapper.deleteAllocationTaskTeachingTasks(ids);
        mapper.deleteAllocationItemAdjustmentLogs(ids);
        mapper.deleteAllocationItems(ids);
        // course_assignment is the immutable formal timetable ledger. A hard
        // delete must never erase it (or its adjustment history). If inactive
        // history still references this task, the teaching_task FK rejects the
        // final delete and Spring rolls this whole transaction back.
    }

    /**
     * Check the complete batch before the first mutation. Every guard call
     * acquires the global publication row lock and checks ACTIVE formal
     * assignments on the same Spring transaction/connection. This serializes
     * the check with concurrent scheme confirmation.
     */
    private void rejectPublishedReferences(EntityTarget target, List<Long> ids) {
        for (Long id : ids) {
            switch (target.tableName()) {
                case "teacher" -> formalScheduleMutationGuard.lockAndRejectTeacher(id);
                case "classroom" -> formalScheduleMutationGuard.lockAndRejectClassroom(id);
                case "course" -> formalScheduleMutationGuard.lockAndRejectCourse(id);
                case "class_group" -> formalScheduleMutationGuard.lockAndRejectClassGroup(id);
                case "teaching_task" -> formalScheduleMutationGuard.lockAndRejectTeachingTask(id);
                default -> throw new IllegalStateException("未配置正式课表冻结规则: " + target.tableName());
            }
        }
    }

    /**
     * Inactive assignments remain part of the formal timetable audit ledger.
     * They no longer freeze ordinary edits, but their referenced master data
     * still cannot be hard-deleted.
     */
    private void rejectFormalHistoryDeletion(EntityTarget target, List<Long> ids) {
        int historyCount = switch (target.tableName()) {
            case "teacher" -> mapper.countAssignmentHistoryByTeacherIds(ids);
            case "classroom" -> mapper.countAssignmentHistoryByClassroomIds(ids);
            case "course" -> mapper.countAssignmentHistoryByCourseIds(ids);
            case "class_group" -> mapper.countAssignmentHistoryByClassGroupIds(ids);
            case "teaching_task" -> mapper.countAssignmentHistoryByTeachingTaskIds(ids);
            default -> throw new IllegalStateException("未配置正式课表历史保护规则: " + target.tableName());
        };
        if (historyCount > 0) {
            throw new ConflictException("选中数据存在正式课表历史记录；可禁用，但不能永久删除");
        }
    }

    private EntityTarget target(String entity) {
        EntityTarget target = TARGETS.get(entity);
        if (target == null) {
            throw new ValidationException("不支持的管理数据类型: " + entity);
        }
        return target;
    }

    private List<Long> normalizeIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            throw new ValidationException("请选择要处理的数据");
        }
        List<Long> normalized = ids.stream()
                .filter(id -> id != null && id > 0)
                .distinct()
                .toList();
        if (normalized.isEmpty()) {
            throw new ValidationException("请选择有效的数据");
        }
        return normalized;
    }

    private record EntityTarget(String tableName, boolean disableSupported) {
    }
}
