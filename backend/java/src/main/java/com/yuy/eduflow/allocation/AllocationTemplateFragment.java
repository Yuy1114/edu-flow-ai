package com.yuy.eduflow.allocation;

import lombok.Data;

/**
 * V3.5 模板草案中的一个可编辑授课片段。
 *
 * <p>片段属于一张模板；模板映射到哪些教学周由
 * {@code schedule_template_week} 决定。数据库主键就是草案编辑 API
 * 使用的稳定 ID，不再伪装成旧版 {@code allocation_item}。</p>
 */
@Data
public class AllocationTemplateFragment {
	private Long id;
	private Long templateId;
	private String templateCode;
	private Long allocationTaskId;
	private String generationRunId;
	private String fragmentCode;
	private Long teachingTaskId;
	private String sourceKey;
	private Long courseId;
	private String courseName;
	private Long teacherId;
	private String teacherName;
	private Long classGroupId;
	private String className;
	private Long classroomId;
	private String classroomName;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Integer consecutiveSlots;
	private Integer durationWeeks;
	private Integer sessionHours;
	private String requiredRoomType;
	private String sourceType;
	private String lockStatus;
}
