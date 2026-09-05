package com.yuy.eduflow.assignment;

import com.yuy.eduflow.enums.AssignmentStatus;
import java.time.LocalDateTime;
import lombok.Data;

/**
 * 正式课表记录（v2）。
 * 数据库字段：id, source_scheme_id, teaching_task_id, classroom_id, time_slot_id, status。
 * teacherId / classGroupId / courseId 为兼容调课模块的派生字段，由 Mapper 查询时填充。
 */
@Data
public class CourseAssignment {
	private Long id;
	private Long sourceSchemeId;
	private Long teachingTaskId;
	private Long classroomId;
	private Long timeSlotId;
	/** 一次课实际占用的45分钟原子节次数；人工补尾课时允许为1。 */
	private Integer consecutiveSlots;
    private AssignmentStatus status;
	private LocalDateTime createdAt;
	private LocalDateTime updatedAt;

	// 以下字段非数据库持久化，由 Mapper JOIN teaching_task 时填充，供调课模块兼容使用
	private Long teacherId;
	private Long classGroupId;
	private Long courseId;
}
