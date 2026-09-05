package com.yuy.eduflow.maintenance;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.common.exception.ValidationException;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Delete;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.annotation.Transactional;

@ExtendWith(MockitoExtension.class)
class MaintenanceCleanupServiceTest {
    @Mock private MaintenanceCleanupMapper mapper;

    @Test
    void clearsEveryV35LifecycleTableAndRebuildsAdminInDependencyOrder() {
        when(mapper.tableExists(anyString())).thenReturn(1);
        when(mapper.insertAdmin("root-admin", "secret", "教务管理员")).thenReturn(1);
        when(mapper.countCoreTables()).thenReturn(List.of(Map.of("table_name", "teacher", "row_count", 1L)));
        MaintenanceCleanupService service = new MaintenanceCleanupService(mapper);

        Map<String, Object> result = service.cleanupTestData(new MaintenanceCleanupRequest(
                "清理测试数据", "root-admin", "secret", "教务管理员"));

        assertEquals("ok", result.get("status"));
        @SuppressWarnings("unchecked")
        List<String> clearedTables = (List<String>) result.get("clearedTables");
        assertTrue(clearedTables.containsAll(List.of(
                "schedule_timetable_entry",
                "schedule_template_fragment_week",
                "schedule_template_fragment_slot",
                "schedule_template_fragment_teacher",
                "schedule_template_fragment_class_group",
                "schedule_template_week",
                "schedule_template_fragment",
                "schedule_template",
                "schedule_generation_run",
                "teacher_department")));

        InOrder order = inOrder(mapper);
        order.verify(mapper).deleteAllScheduleTimetableEntries();
        order.verify(mapper).deleteAllScheduleTemplateFragmentWeeks();
        order.verify(mapper).deleteAllScheduleTemplateFragmentSlots();
        order.verify(mapper).deleteAllScheduleTemplateFragmentTeachers();
        order.verify(mapper).deleteAllScheduleTemplateFragmentClassGroups();
        order.verify(mapper).deleteAllScheduleTemplateWeeks();
        order.verify(mapper).deleteAllScheduleTemplateFragments();
        order.verify(mapper).deleteAllScheduleTemplates();
        order.verify(mapper).deleteAllScheduleGenerationRuns();
        order.verify(mapper).deleteAllAllocationTasks();
        order.verify(mapper).deleteAllTeacherProfiles();
        order.verify(mapper).deleteAllTeacherDepartments();
        order.verify(mapper).deleteAllTeachers();
        order.verify(mapper).insertAdmin("root-admin", "secret", "教务管理员");
        order.verify(mapper).countCoreTables();
    }

    @Test
    void cleanupIsTransactionalAndAllDestructiveStatementsAreRollbackCapableDeletes() throws Exception {
        Method cleanup = MaintenanceCleanupService.class.getMethod(
                "cleanupTestData", MaintenanceCleanupRequest.class);
        assertNotNull(cleanup.getAnnotation(Transactional.class));

        Arrays.stream(MaintenanceCleanupMapper.class.getDeclaredMethods())
                .filter(method -> method.getName().startsWith("deleteAll"))
                .forEach(method -> {
                    Delete annotation = method.getAnnotation(Delete.class);
                    assertNotNull(annotation, method.getName() + " 必须显式声明 DELETE SQL");
                    String sql = String.join(" ", annotation.value()).trim().toUpperCase();
                    assertTrue(sql.startsWith("DELETE FROM "), method.getName() + " 不是 DELETE");
                    assertTrue(!sql.contains("TRUNCATE"), "事务清理不得使用会隐式提交的 TRUNCATE");
                });
    }

    @Test
    void invalidConfirmationPerformsNoDatabaseOperation() {
        MaintenanceCleanupService service = new MaintenanceCleanupService(mapper);

        assertThrows(ValidationException.class, () -> service.cleanupTestData(
                new MaintenanceCleanupRequest("删除", null, null, null)));

        verifyNoInteractions(mapper);
    }

    @Test
    void aMissingOptionalTableIsReportedAsSkippedAndNotDeleted() {
        when(mapper.tableExists(anyString())).thenReturn(1);
        when(mapper.tableExists("ml_training_log")).thenReturn(0);
        when(mapper.insertAdmin("admin", "admin123", "系统管理员")).thenReturn(1);
        when(mapper.countCoreTables()).thenReturn(List.of());
        MaintenanceCleanupService service = new MaintenanceCleanupService(mapper);

        Map<String, Object> result = service.cleanupTestData(
                new MaintenanceCleanupRequest("清理测试数据", null, null, null));

        @SuppressWarnings("unchecked")
        List<String> clearedTables = (List<String>) result.get("clearedTables");
        assertTrue(!clearedTables.contains("ml_training_log"));
        verify(mapper, never()).deleteAllLegacyMlTrainingLogs();
    }
}
