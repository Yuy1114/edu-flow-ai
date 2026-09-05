package com.yuy.eduflow.allocation;

import lombok.Data;

/** 确认 V3.5 方案时要物化的一次课（保存起始原子时间片）。 */
@Data
public class AllocationTemplateSession {
	private Integer weekNumber;
	private Long templateId;
	private Long templateFragmentId;
	private Long teachingTaskId;
	private Long classroomId;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Integer consecutiveSlots;
	private Long timeSlotId;
}
