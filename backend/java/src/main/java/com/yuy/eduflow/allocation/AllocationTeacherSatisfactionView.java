package com.yuy.eduflow.allocation;

import java.util.List;
import java.util.Map;

/**
 * 方案详情页要看的画像满足度：整体读数 + 低满足教师明细。
 *
 * <p>{@code lowSatisfaction} 不是在这里判出来的——生成侧（Python
 * {@code teacher_preferences.LOW_SATISFACTION_THRESHOLD}）判完落库，展示端只读，
 * 免得同一位教师在两处得到不同结论。</p>
 */
public record AllocationTeacherSatisfactionView(
	boolean profileApplied,
	int teacherCount,
	double averageSatisfactionScore,
	double averagePreferenceScore,
	int lowSatisfactionCount,
	List<TeacherSatisfactionEntry> teachers,
	List<TeacherSatisfactionEntry> lowSatisfactionTeachers
) {

	public static final AllocationTeacherSatisfactionView EMPTY = new AllocationTeacherSatisfactionView(
		false, 0, 0.0, 0.0, 0,
		List.of(), List.of()
	);

	/**
	 * @param primaryReasonDimension 已声明维度里得分最低的那一维，即"主因"；没有声明过就是 null。
	 * @param primaryReasonScore     主因维度的得分。
	 */
	public record TeacherSatisfactionEntry(
		String templateCode,
		String teacherKey,
		Long teacherId,
		String teacherName,
		int itemCount,
		int daysUsed,
		double satisfactionScore,
		double preferenceScore,
		boolean lowSatisfaction,
		List<String> declaredDimensions,
		String primaryReasonDimension,
		Double primaryReasonScore,
		Map<String, Double> components,
		Map<String, Object> evidence
	) {
	}
}
