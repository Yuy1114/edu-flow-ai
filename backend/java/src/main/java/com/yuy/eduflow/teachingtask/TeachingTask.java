package com.yuy.eduflow.teachingtask;

import com.yuy.eduflow.classgroup.ClassGroup;
import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.teacher.Teacher;
import java.time.LocalDateTime;
import com.yuy.eduflow.enums.ActiveStatus;
import java.util.List;
import lombok.Data;

@Data
public class TeachingTask {
    private Long id;
    private Long courseId;
    private Long primaryTeacherId;
    private Long assistantTeacherId;
    private Long classroomId;
    private Integer totalHours;
    private Integer sessionsPerWeek;
    private Integer durationWeeks;
    private String requiredRoomType;
    private String taskBatch;
    private String notes;
    private ActiveStatus status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    // 非数据库字段
    private Course course;
    private Teacher primaryTeacher;
    private Teacher assistantTeacher;
    private Classroom classroom;
    private List<ClassGroup> classGroups;
}
