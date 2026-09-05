package com.yuy.eduflow.management;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ConflictException;
import java.util.Arrays;
import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ManagementBatchServiceTest {
    @Mock private ManagementBatchMapper mapper;
    @Mock private FormalScheduleMutationGuard formalScheduleMutationGuard;
    @InjectMocks private ManagementBatchService service;

    @Test
    void checksTheWholeBatchAgainstThePublicationGuardBeforeDisabling() {
        when(mapper.updateStatus("teacher", List.of(3L, 4L), "INACTIVE")).thenReturn(2);

        int affected = service.disable("teachers", List.of(3L, 3L, 4L));

        assertEquals(2, affected);
        InOrder order = inOrder(formalScheduleMutationGuard, mapper);
        order.verify(formalScheduleMutationGuard).lockAndRejectTeacher(3L);
        order.verify(formalScheduleMutationGuard).lockAndRejectTeacher(4L);
        order.verify(mapper).updateStatus("teacher", List.of(3L, 4L), "INACTIVE");
    }

    @Test
    void anActiveFormalReferenceRejectsTheCompleteDeleteBeforeAnyMutation() {
        doThrow(new ConflictException("课程已被正式课表引用"))
                .when(formalScheduleMutationGuard).lockAndRejectCourse(8L);

        assertThrows(ConflictException.class, () -> service.delete("courses", List.of(8L, 9L)));

        verify(formalScheduleMutationGuard).lockAndRejectCourse(8L);
        verify(formalScheduleMutationGuard, never()).lockAndRejectCourse(9L);
        verifyNoInteractions(mapper);
    }

    @Test
    void teachingTaskDeleteOnlyRemovesDraftDependenciesAndNeverTheFormalLedger() {
        when(mapper.deleteRows("teaching_task", List.of(11L))).thenReturn(1);

        int affected = service.delete("teaching-tasks", List.of(11L));

        assertEquals(1, affected);
        InOrder order = inOrder(formalScheduleMutationGuard, mapper);
        order.verify(formalScheduleMutationGuard).lockAndRejectTeachingTask(11L);
        order.verify(mapper).countAssignmentHistoryByTeachingTaskIds(List.of(11L));
        order.verify(mapper).detachConflictCheckResults(List.of(11L));
        order.verify(mapper).detachMlFeedbackEvents(List.of(11L));
        order.verify(mapper).deleteAllocationTaskTeachingTasks(List.of(11L));
        order.verify(mapper).deleteAllocationItemAdjustmentLogs(List.of(11L));
        order.verify(mapper).deleteAllocationItems(List.of(11L));
        order.verify(mapper).deleteRows("teaching_task", List.of(11L));

        boolean mapperCanDeleteFormalAssignments = Arrays.stream(ManagementBatchMapper.class.getDeclaredMethods())
                .map(method -> method.getAnnotation(Delete.class))
                .filter(annotation -> annotation != null)
                .flatMap(annotation -> Arrays.stream(annotation.value()))
                .map(String::toLowerCase)
                .anyMatch(sql -> sql.contains("delete from course_assignment"));
        assertFalse(mapperCanDeleteFormalAssignments,
                "批量管理 Mapper 不得提供删除正式课表台账的 SQL");
    }

    @Test
    void inactiveFormalHistoryAlsoRejectsPermanentDeletionWithoutErasingTheLedger() {
        when(mapper.countAssignmentHistoryByClassroomIds(List.of(12L))).thenReturn(1);

        assertThrows(ConflictException.class,
                () -> service.delete("classrooms", List.of(12L)));

        InOrder order = inOrder(formalScheduleMutationGuard, mapper);
        order.verify(formalScheduleMutationGuard).lockAndRejectClassroom(12L);
        order.verify(mapper).countAssignmentHistoryByClassroomIds(List.of(12L));
        verify(mapper, never()).deleteRows("classroom", List.of(12L));
    }

    @Test
    void everySupportedEntityUsesItsTypedFormalScheduleGuard() {
        when(mapper.updateStatus("classroom", List.of(1L), "INACTIVE")).thenReturn(1);
        when(mapper.updateStatus("course", List.of(2L), "INACTIVE")).thenReturn(1);
        when(mapper.updateStatus("teaching_task", List.of(3L), "INACTIVE")).thenReturn(1);
        when(mapper.deleteRows("class_group", List.of(4L))).thenReturn(1);

        service.disable("classrooms", List.of(1L));
        service.disable("courses", List.of(2L));
        service.disable("teaching-tasks", List.of(3L));
        service.delete("class-groups", List.of(4L));

        verify(formalScheduleMutationGuard).lockAndRejectClassroom(1L);
        verify(formalScheduleMutationGuard).lockAndRejectCourse(2L);
        verify(formalScheduleMutationGuard).lockAndRejectTeachingTask(3L);
        verify(formalScheduleMutationGuard).lockAndRejectClassGroup(4L);
    }
}
