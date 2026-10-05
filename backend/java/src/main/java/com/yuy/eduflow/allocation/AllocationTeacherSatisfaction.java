package com.yuy.eduflow.allocation;

import lombok.Data;

/**
 * 方案级的教师画像满足度留痕（表 {@code schedule_teacher_satisfaction}）。
 *
 * <p>一行 = 一个动态模板里的一位教师。动态模板就是一份候选方案，各覆盖不同周次，
 * 所以分数必须按模板分开看；两份分数各管一件事，见列注释与
 * {@code docs/implementation/14-教师画像候选排序接入.md}。</p>
 */
@Data
public class AllocationTeacherSatisfaction {
	private Long id;
	private Long allocationTaskId;
	private String generationRunId;
	private String templateCode;
	private String teacherKey;
	private Long teacherId;
	private String teacherName;
	private Integer itemCount;
	private Integer daysUsed;
	private Double satisfactionScore;
	private Double preferenceScore;
	private Boolean lowSatisfaction;
	private String declaredDimensionsJson;
	private String componentsJson;
	private String evidenceJson;
}
