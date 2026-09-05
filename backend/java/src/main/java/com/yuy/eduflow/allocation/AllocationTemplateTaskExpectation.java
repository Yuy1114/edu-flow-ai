package com.yuy.eduflow.allocation;

import lombok.Data;

@Data
public class AllocationTemplateTaskExpectation {
	private Long teachingTaskId;
	private String courseName;
	private Integer requiredHours;
	private String courseType;
	private Integer sessionPeriods;
	private String teachingTaskStatus;
	private String courseStatus;
}
