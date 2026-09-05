package com.yuy.eduflow.teachingtask;

import java.util.List;

public record TeachingTaskRequest(
        Long courseId,
        Long primaryTeacherId,
        Long assistantTeacherId,
        Long classroomId,
        Integer totalHours,
        Integer sessionsPerWeek,
        Integer durationWeeks,
        String requiredRoomType,
        String taskBatch,
        String notes,
        String status,
        List<Long> classGroupIds,
        List<Long> candidateClassroomIds) {
}
