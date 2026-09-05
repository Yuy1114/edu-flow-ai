package com.yuy.eduflow.allocation;

import lombok.Data;
import java.util.List;

/**
 * 分课方案明细视图，展开教学任务、教室、时间段信息。
 */
@Data
public class AllocationItemView {
	private Long id;
	/** V3.5 草案片段的真实主键；旧方案为 null。 */
	private Long templateFragmentId;
	private Long templateId;
	private String fragmentCode;
	private Long schemeId;
	private Long teachingTaskId;
	private String courseName;
	private String teacherName;
	private String classGroupName;
	private Long classroomId;
	private String classroomName;
	private Long timeSlotId;
	private String timeSlotLabel;
	private Integer weekNumber;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Double teacherProfileScore;
	private Double teacherProfilePenalty;
	private String teacherProfileReasonsJson;
	private String teacherProfileComponentsJson;
	private Boolean valid;
	private String conflictMessage;
	private Integer consecutiveSlots;
	private Integer durationWeeks;
	private List<Integer> weekNumbers;
	private String sourceType;
}
