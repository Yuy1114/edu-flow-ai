package com.yuy.eduflow.allocation;

import lombok.Data;

/** 一条已经展开到“绝对周 + 45 分钟原子节次”的模板占用。 */
@Data
public class AllocationTemplateAuditEntry {
	private Integer weekNumber;
	private Long templateId;
	private String templateCode;
	private Long templateFragmentId;
	private String fragmentCode;
	private Long teachingTaskId;
	private String courseName;
	private String teacherIds;
	private String teacherName;
	private String classGroupIds;
	private String className;
	private Long classroomId;
	private String classroomName;
	private Integer classroomCapacity;
	private String classroomType;
	private String classroomStatus;
	private Integer studentCount;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Integer startDayOfWeek;
	private Integer startPeriodIndex;
	private Integer consecutiveSlots;
	private Integer durationWeeks;
	private String courseType;
	private Integer expectedSessionPeriods;
	private String teachingTaskStatus;
	private String courseStatus;
	private String primaryTeacherStatus;
	private String assistantTeacherStatus;
	private String primaryAvailabilityMatrixJson;
	private String assistantAvailabilityMatrixJson;
	private Boolean teacherHardUnavailable;
	private Boolean classroomAllowed;
	private Boolean teacherRelationsCurrent;
	private Boolean classGroupRelationsCurrent;
	private String requiredRoomType;
	private String sourceType;
}
