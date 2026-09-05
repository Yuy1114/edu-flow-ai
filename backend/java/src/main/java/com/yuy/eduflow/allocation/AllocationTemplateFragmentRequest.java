package com.yuy.eduflow.allocation;

import java.util.List;

/**
 * 人工新增或调整模板片段的请求。
 *
 * <p>新增时 templateId、teachingTaskId 必填；调整时二者保持不变。
 * {@code weekNumbers} 是权威的精确生效周集合，可表达任意单周或非连续周；
 * {@code durationWeeks} 仅为兼容旧草案的回退字段。人工补排可显式使用
 * {@code consecutiveSlots=1}，自动生成仍使用课程默认的2/4节块。</p>
 */
public record AllocationTemplateFragmentRequest(
	Long templateId,
	Long teachingTaskId,
	Long classroomId,
	Integer dayOfWeek,
	Integer periodIndex,
	Integer consecutiveSlots,
	Integer durationWeeks,
	List<Integer> weekNumbers,
	String reason
) {
}
