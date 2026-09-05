package com.yuy.eduflow.maintenance;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface MaintenanceCleanupMapper {
    @Select("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = #{tableName}")
    int tableExists(@Param("tableName") String tableName);

    @Delete("DELETE FROM allocation_item_adjustment_log")
    void deleteAllAllocationItemAdjustmentLogs();

    @Delete("DELETE FROM adjustment_request")
    void deleteAllAdjustmentRequests();

    @Delete("DELETE FROM conflict_check_result")
    void deleteAllConflictCheckResults();

    @Delete("DELETE FROM course_assignment")
    void deleteAllCourseAssignments();

    @Delete("DELETE FROM allocation_scheme_feedback")
    void deleteAllAllocationSchemeFeedback();

    @Delete("DELETE FROM ml_feedback_event")
    void deleteAllMlFeedbackEvents();

    @Delete("DELETE FROM model_training_log")
    void deleteAllModelTrainingLogs();

    @Delete("DELETE FROM ml_training_log")
    void deleteAllLegacyMlTrainingLogs();

    @Delete("DELETE FROM allocation_item")
    void deleteAllAllocationItems();

    @Delete("DELETE FROM schedule_timetable_entry")
    void deleteAllScheduleTimetableEntries();

    @Delete("DELETE FROM schedule_template_fragment_week")
    void deleteAllScheduleTemplateFragmentWeeks();

    @Delete("DELETE FROM schedule_template_fragment_slot")
    void deleteAllScheduleTemplateFragmentSlots();

    @Delete("DELETE FROM schedule_template_fragment_teacher")
    void deleteAllScheduleTemplateFragmentTeachers();

    @Delete("DELETE FROM schedule_template_fragment_class_group")
    void deleteAllScheduleTemplateFragmentClassGroups();

    @Delete("DELETE FROM schedule_template_week")
    void deleteAllScheduleTemplateWeeks();

    @Delete("DELETE FROM schedule_template_fragment")
    void deleteAllScheduleTemplateFragments();

    @Delete("DELETE FROM schedule_template")
    void deleteAllScheduleTemplates();

    @Delete("DELETE FROM schedule_generation_run")
    void deleteAllScheduleGenerationRuns();

    @Delete("DELETE FROM allocation_scheme")
    void deleteAllAllocationSchemes();

    @Delete("DELETE FROM allocation_task_generation_config")
    void deleteAllAllocationTaskGenerationConfigs();

    @Delete("DELETE FROM allocation_task_teaching_task")
    void deleteAllAllocationTaskTeachingTasks();

    @Delete("DELETE FROM allocation_task")
    void deleteAllAllocationTasks();

    @Delete("DELETE FROM teaching_task_classroom")
    void deleteAllTeachingTaskClassrooms();

    @Delete("DELETE FROM teaching_task_class_group")
    void deleteAllTeachingTaskClassGroups();

    @Delete("DELETE FROM teaching_task")
    void deleteAllTeachingTasks();

    @Delete("DELETE FROM teacher_profile")
    void deleteAllTeacherProfiles();

    @Delete("DELETE FROM teacher_department")
    void deleteAllTeacherDepartments();

    @Delete("DELETE FROM course")
    void deleteAllCourses();

    @Delete("DELETE FROM classroom")
    void deleteAllClassrooms();

    @Delete("DELETE FROM class_group")
    void deleteAllClassGroups();

    @Delete("DELETE FROM teacher")
    void deleteAllTeachers();

    @Insert("""
        INSERT INTO teacher (employee_no, password, role, name, department, title, status)
        VALUES (#{employeeNo}, #{password}, 'ADMIN', #{name}, '系统管理', '管理员', 'ACTIVE')
        """)
    int insertAdmin(@Param("employeeNo") String employeeNo, @Param("password") String password, @Param("name") String name);

    @Select("""
        SELECT 'course' AS table_name, COUNT(*) AS row_count FROM course
        UNION ALL SELECT 'teacher', COUNT(*) FROM teacher
        UNION ALL SELECT 'classroom', COUNT(*) FROM classroom
        UNION ALL SELECT 'class_group', COUNT(*) FROM class_group
        UNION ALL SELECT 'teaching_task', COUNT(*) FROM teaching_task
        UNION ALL SELECT 'allocation_task', COUNT(*) FROM allocation_task
        """)
    List<Map<String, Object>> countCoreTables();
}
