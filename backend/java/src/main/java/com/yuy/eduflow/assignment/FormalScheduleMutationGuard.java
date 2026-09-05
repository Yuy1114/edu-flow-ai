package com.yuy.eduflow.assignment;

import com.yuy.eduflow.common.exception.ConflictException;
import org.springframework.stereotype.Component;

/**
 * Fail-closed guard for reference data used by an ACTIVE formal timetable.
 * Until assignment resource snapshots are stored as first-class relations, the
 * referenced scheduling identity is immutable and may only be changed after the
 * formal assignments have been made inactive.
 */
@Component
public class FormalScheduleMutationGuard {
	private final CourseAssignmentMapper assignmentMapper;

	public FormalScheduleMutationGuard(CourseAssignmentMapper assignmentMapper) {
		this.assignmentMapper = assignmentMapper;
	}

	public void lockAndRejectTeachingTask(Long id) {
		assignmentMapper.lockSchedulePublication();
		reject(assignmentMapper.countActiveByTeachingTask(id), "教学任务");
	}

	public void lockAndRejectTeacher(Long id) {
		assignmentMapper.lockSchedulePublication();
		reject(assignmentMapper.countActiveByTeacher(id), "教师");
	}

	public void lockAndRejectClassroom(Long id) {
		assignmentMapper.lockSchedulePublication();
		reject(assignmentMapper.countActiveByClassroom(id), "教室");
	}

	public void lockAndRejectCourse(Long id) {
		assignmentMapper.lockSchedulePublication();
		reject(assignmentMapper.countActiveByCourse(id), "课程");
	}

	public void lockAndRejectClassGroup(Long id) {
		assignmentMapper.lockSchedulePublication();
		reject(assignmentMapper.countActiveByClassGroup(id), "班级");
	}

	private void reject(int activeAssignments, String resourceType) {
		if (activeAssignments > 0) {
			throw new ConflictException(
				resourceType + "已被正式课表引用；请先撤销相关正式安排，再修改排课关键数据"
			);
		}
	}
}
