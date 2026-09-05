package com.yuy.eduflow.assignment;

import com.yuy.eduflow.enums.AssignmentStatus;
import lombok.Data;

@Data
public class CourseAssignmentView {
	private Long id;
	private Long teachingTaskId;
	private Long courseId;
	private String courseName;
	private Long classGroupId;
	private String classGroupName;
	private Long teacherId;
	private String teacherName;
	private Long classroomId;
	private String classroomName;
	private Long timeSlotId;
	private String timeSlotLabel;
	private Integer weekNumber;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Integer consecutiveSlots;
	private Long sourceSchemeId;
    private AssignmentStatus status;
}
