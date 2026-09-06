package com.yuy.eduflow.assignment;

import com.yuy.eduflow.enums.AssignmentStatus;
import lombok.Data;

@Data
public class CourseAssignmentView {
	private Long id;
	private Long teachingTaskId;
	private Long courseId;
	private String courseName;
	private Long classGroupId;
	private String classGroupName;
	/** 合班任务的全部班级 ID，逗号分隔；{@code classGroupId} 只是其中第一个。 */
	private String classGroupIds;
	private Long teacherId;
	private String teacherName;
	/**
	 * 主讲与助教分开保存。{@code teacherName} 是二者的合并展示串，
	 * 按单个教师导出课表时必须用这两个 ID 判断归属，否则助教的课会被算到主讲名下。
	 */
	private Long primaryTeacherId;
	private String primaryTeacherName;
	private Long assistantTeacherId;
	private String assistantTeacherName;
	private Long classroomId;
	private String classroomName;
	private Long timeSlotId;
	private String timeSlotLabel;
	private Integer weekNumber;
	private Integer dayOfWeek;
	private Integer periodIndex;
	private Integer consecutiveSlots;
	private Long sourceSchemeId;
    private AssignmentStatus status;
}
