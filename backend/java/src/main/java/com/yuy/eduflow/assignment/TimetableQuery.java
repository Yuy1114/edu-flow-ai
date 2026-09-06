package com.yuy.eduflow.assignment;

/**
 * 正式课表的组合查询条件。
 *
 * <p>全部字段可空，空即不限制。{@code allocationTaskId} 按排课任务过滤，
 * 用于把一次排课发布出去的课表单独取出来；其余维度是教务日常查询的角色维度。</p>
 */
public record TimetableQuery(
	Long teacherId,
	Long classGroupId,
	Long courseId,
	Long classroomId,
	Long allocationTaskId,
	Integer weekNumber,
	Integer dayOfWeek,
	String status
) {
	public static TimetableQuery of(Long teacherId, Long classGroupId, Long courseId, Long classroomId,
		Long allocationTaskId, Integer weekNumber, Integer dayOfWeek, String status) {
		return new TimetableQuery(teacherId, classGroupId, courseId, classroomId,
			allocationTaskId, weekNumber, dayOfWeek, status);
	}

	public TimetableQuery withStatus(String replacement) {
		return new TimetableQuery(teacherId, classGroupId, courseId, classroomId,
			allocationTaskId, weekNumber, dayOfWeek, replacement);
	}

	public TimetableQuery withTeacherId(Long replacement) {
		return new TimetableQuery(replacement, classGroupId, courseId, classroomId,
			allocationTaskId, weekNumber, dayOfWeek, status);
	}

	public TimetableQuery withClassGroupId(Long replacement) {
		return new TimetableQuery(teacherId, replacement, courseId, classroomId,
			allocationTaskId, weekNumber, dayOfWeek, status);
	}

	public TimetableQuery withClassroomId(Long replacement) {
		return new TimetableQuery(teacherId, classGroupId, courseId, replacement,
			allocationTaskId, weekNumber, dayOfWeek, status);
	}
}
