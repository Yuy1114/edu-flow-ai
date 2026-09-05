package com.yuy.eduflow.maintenance;

import com.yuy.eduflow.common.exception.ValidationException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MaintenanceCleanupService {
    private static final String CONFIRM_TEXT = "清理测试数据";

    private final MaintenanceCleanupMapper mapper;

    public MaintenanceCleanupService(MaintenanceCleanupMapper mapper) {
        this.mapper = mapper;
    }

    @Transactional
    public Map<String, Object> cleanupTestData(MaintenanceCleanupRequest request) {
        if (request == null || !CONFIRM_TEXT.equals(request.confirmText())) {
            throw new ValidationException("确认文本不正确，请输入：" + CONFIRM_TEXT);
        }
        String employeeNo = defaultString(request.adminEmployeeNo(), "admin");
        String password = defaultString(request.adminPassword(), "admin123");
        String name = defaultString(request.adminName(), "系统管理员");

        // DELETE is intentional: TRUNCATE performs an implicit commit in
        // MySQL and would leave a half-cleared database if a later step fails.
        // Ordered deletes and the Spring transaction keep every statement on
        // one transaction-bound MyBatis connection and make the reset atomic.
        List<String> clearedTables = deleteAll();
        mapper.insertAdmin(employeeNo, password, name);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "ok");
        result.put("adminEmployeeNo", employeeNo);
        result.put("adminName", name);
        result.put("counts", mapper.countCoreTables());
        result.put("clearedTables", clearedTables);
        return result;
    }

    private List<String> deleteAll() {
        List<String> cleared = new ArrayList<>();

        // Published/adjustment facts first.
        deleteIfExists("allocation_item_adjustment_log", mapper::deleteAllAllocationItemAdjustmentLogs, cleared);
        deleteIfExists("adjustment_request", mapper::deleteAllAdjustmentRequests, cleared);
        deleteIfExists("conflict_check_result", mapper::deleteAllConflictCheckResults, cleared);
        deleteIfExists("course_assignment", mapper::deleteAllCourseAssignments, cleared);
        deleteIfExists("allocation_scheme_feedback", mapper::deleteAllAllocationSchemeFeedback, cleared);
        deleteIfExists("ml_feedback_event", mapper::deleteAllMlFeedbackEvents, cleared);
        deleteIfExists("model_training_log", mapper::deleteAllModelTrainingLogs, cleared);
        // Compatibility with an early Python-only training ledger.
        deleteIfExists("ml_training_log", mapper::deleteAllLegacyMlTrainingLogs, cleared);
        deleteIfExists("allocation_item", mapper::deleteAllAllocationItems, cleared);

        // V3.5 dynamic-template projections and multi-value relations.
        deleteIfExists("schedule_timetable_entry", mapper::deleteAllScheduleTimetableEntries, cleared);
        deleteIfExists("schedule_template_fragment_week", mapper::deleteAllScheduleTemplateFragmentWeeks, cleared);
        deleteIfExists("schedule_template_fragment_slot", mapper::deleteAllScheduleTemplateFragmentSlots, cleared);
        deleteIfExists("schedule_template_fragment_teacher", mapper::deleteAllScheduleTemplateFragmentTeachers, cleared);
        deleteIfExists("schedule_template_fragment_class_group", mapper::deleteAllScheduleTemplateFragmentClassGroups, cleared);
        deleteIfExists("schedule_template_week", mapper::deleteAllScheduleTemplateWeeks, cleared);
        deleteIfExists("schedule_template_fragment", mapper::deleteAllScheduleTemplateFragments, cleared);
        deleteIfExists("schedule_template", mapper::deleteAllScheduleTemplates, cleared);

        // Generation lifecycle and allocation ownership.
        deleteIfExists("schedule_generation_run", mapper::deleteAllScheduleGenerationRuns, cleared);
        deleteIfExists("allocation_scheme", mapper::deleteAllAllocationSchemes, cleared);
        deleteIfExists("allocation_task_generation_config", mapper::deleteAllAllocationTaskGenerationConfigs, cleared);
        deleteIfExists("allocation_task_teaching_task", mapper::deleteAllAllocationTaskTeachingTasks, cleared);
        deleteIfExists("allocation_task", mapper::deleteAllAllocationTasks, cleared);

        // Teaching master data, children before parents.
        deleteIfExists("teaching_task_classroom", mapper::deleteAllTeachingTaskClassrooms, cleared);
        deleteIfExists("teaching_task_class_group", mapper::deleteAllTeachingTaskClassGroups, cleared);
        deleteIfExists("teaching_task", mapper::deleteAllTeachingTasks, cleared);
        deleteIfExists("teacher_profile", mapper::deleteAllTeacherProfiles, cleared);
        deleteIfExists("teacher_department", mapper::deleteAllTeacherDepartments, cleared);
        deleteIfExists("course", mapper::deleteAllCourses, cleared);
        deleteIfExists("classroom", mapper::deleteAllClassrooms, cleared);
        deleteIfExists("class_group", mapper::deleteAllClassGroups, cleared);
        deleteIfExists("teacher", mapper::deleteAllTeachers, cleared);
        // time_slot, schedule_publication_lock and schema_migration are
        // infrastructure catalogs, not test data, and are deliberately kept.
        return List.copyOf(cleared);
    }

    private void deleteIfExists(String tableName, Runnable delete, List<String> cleared) {
        if (mapper.tableExists(tableName) > 0) {
            delete.run();
            cleared.add(tableName);
        }
    }

    private String defaultString(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value.trim();
    }
}
