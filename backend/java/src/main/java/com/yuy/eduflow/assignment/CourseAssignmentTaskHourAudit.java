package com.yuy.eduflow.assignment;

import lombok.Data;

@Data
public class CourseAssignmentTaskHourAudit {
	private Long teachingTaskId;
	private String courseName;
	private Integer requiredHours;
	private Integer scheduledHours;
	private Integer deltaHours;
	private String status;
}
