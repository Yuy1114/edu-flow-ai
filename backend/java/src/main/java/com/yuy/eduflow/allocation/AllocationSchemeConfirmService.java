package com.yuy.eduflow.allocation;

import com.yuy.eduflow.assignment.CourseAssignment;
import com.yuy.eduflow.assignment.CourseAssignmentMapper;
import com.yuy.eduflow.assignment.CourseAssignmentService;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.ml.MlFeedbackEventService;
import java.util.List;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import com.yuy.eduflow.enums.AssignmentStatus;
import com.yuy.eduflow.enums.SchemeStatus;
import com.yuy.eduflow.enums.TaskStatus;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
public class AllocationSchemeConfirmService {
	
	
	private static final AssignmentStatus ACTIVE_STATUS = AssignmentStatus.ACTIVE;

	private final AllocationSchemeMapper allocationSchemeMapper;
	private final AllocationItemMapper allocationItemMapper;
	private final AllocationTaskMapper allocationTaskMapper;
	private final CourseAssignmentMapper courseAssignmentMapper;
	private final AllocationSchemeFeedbackMapper feedbackMapper;
	private final AllocationItemAdjustmentLogMapper adjustmentLogMapper;
	private final MlFeedbackEventService feedbackEventService;
	private final AllocationTemplateDraftService allocationTemplateDraftService;
	private final CourseAssignmentService courseAssignmentService;

	public AllocationSchemeConfirmService(
		AllocationSchemeMapper allocationSchemeMapper,
		AllocationItemMapper allocationItemMapper,
		AllocationTaskMapper allocationTaskMapper,
		CourseAssignmentMapper courseAssignmentMapper,
		AllocationSchemeFeedbackMapper feedbackMapper,
		AllocationItemAdjustmentLogMapper adjustmentLogMapper,
		MlFeedbackEventService feedbackEventService,
		AllocationTemplateDraftService allocationTemplateDraftService,
		CourseAssignmentService courseAssignmentService
	) {
		this.allocationSchemeMapper = allocationSchemeMapper;
		this.allocationItemMapper = allocationItemMapper;
		this.allocationTaskMapper = allocationTaskMapper;
		this.courseAssignmentMapper = courseAssignmentMapper;
		this.feedbackMapper = feedbackMapper;
		this.adjustmentLogMapper = adjustmentLogMapper;
		this.feedbackEventService = feedbackEventService;
		this.allocationTemplateDraftService = allocationTemplateDraftService;
		this.courseAssignmentService = courseAssignmentService;
	}

	@Transactional
	public AllocationConfirmResult confirm(Long schemeId) {
		// Different allocation tasks may share teachers/classes/rooms. Serialize the
		// final re-audit + materialization window so two transactions cannot both pass
		// against an empty conflict set and then commit conflicting assignments.
		courseAssignmentMapper.lockSchedulePublication();
		AllocationScheme scheme = allocationSchemeMapper.findByIdForUpdate(schemeId);
		if (scheme == null) {
			throw new ResourceNotFoundException("分课方案不存在");
		}
		if (scheme.getStatus() != SchemeStatus.CANDIDATE) {
			throw new ValidationException("只有候选状态的分课方案可以确认发布，当前状态：" + scheme.getStatus());
		}
		AllocationTask task = allocationTaskMapper.findByIdForUpdate(scheme.getTaskId());
		if (task == null) throw new ResourceNotFoundException("分课任务不存在");
		if (task.getStatus() == null) {
			throw new ValidationException("分课任务状态缺失，不能发布方案");
		}
		if (task.getStatus() != TaskStatus.GENERATED
			&& task.getStatus() != TaskStatus.NEEDS_MANUAL_REVIEW) {
			throw new ValidationException("当前分课任务状态不允许发布方案：" + task.getStatus());
		}

		boolean v35 = allocationTemplateDraftService.isV35(scheme);
		if (!v35) {
			throw new ValidationException("第一阶段只允许确认V3.5动态模板方案；旧版allocation_item方案仅保留历史只读查询");
		}
		List<CourseAssignment> assignments = allocationTemplateDraftService.prepareMaterialization(schemeId).stream()
			.map(session -> toAssignment(schemeId, session))
			.toList();

		int inactivatedAssignments = courseAssignmentMapper.inactivateByAllocationTaskId(
			scheme.getTaskId(),
			AssignmentStatus.INACTIVE.code()
		);
		log.info("Confirming allocation scheme: schemeId={}, taskId={}, inactivatedOldAssignments={}",
			schemeId, scheme.getTaskId(), inactivatedAssignments);

		int assignmentCount = 0;
		for (CourseAssignment assignment : assignments) {
			// Old assignments of this allocation task are already inactive. This validation
			// therefore checks every other ACTIVE formal timetable and assignments inserted
			// earlier in this same transaction.
			courseAssignmentService.validateForPublication(assignment);
			int inserted = courseAssignmentMapper.insert(assignment);
			if (inserted != 1) {
				throw new ConflictException("正式课表写入失败");
			}
			assignmentCount++;
		}

		if (allocationSchemeMapper.updateStatusIfCurrent(
			scheme.getId(), SchemeStatus.CANDIDATE.code(), SchemeStatus.CONFIRMED.code()
		) != 1) {
			throw new ConflictException("分课方案状态已变化，发布已取消");
		}
		int rejectedSchemes = allocationSchemeMapper.rejectOtherSelectableSchemes(
			scheme.getTaskId(),
			scheme.getId(),
			SchemeStatus.REJECTED.code()
		);
		log.info("Allocation scheme confirmed: schemeId={}, insertedAssignments={}, rejectedOtherSchemes={}",
			scheme.getId(), assignmentCount, rejectedSchemes);
		if (allocationTaskMapper.updateStatusIfCurrent(
			scheme.getTaskId(), task.getStatus().code(), TaskStatus.CONFIRMED.code()
		) != 1) {
			throw new ConflictException("分课任务状态已变化，发布已取消");
		}

		// 记录确认反馈
		AllocationSchemeFeedback feedback = new AllocationSchemeFeedback();
		feedback.setSchemeId(schemeId);
		feedback.setTaskId(scheme.getTaskId());
		feedback.setFeedbackType("CONFIRMED");
		feedback.setAdjustmentCount(adjustmentLogMapper.countBySchemeId(schemeId));
		feedback.setCreatedBy(null);
		feedbackMapper.insert(feedback);
		feedbackEventService.recordSchemeConfirmed(scheme, feedback.getId());

		return new AllocationConfirmResult(
			scheme.getId(),
			scheme.getTaskId(),
			assignmentCount,
			SchemeStatus.CONFIRMED.code(),
			SchemeStatus.CONFIRMED.code()
		);
	}

	private CourseAssignment toAssignment(Long schemeId, AllocationItem item) {
		CourseAssignment assignment = new CourseAssignment();
		assignment.setSourceSchemeId(schemeId);
		assignment.setTeachingTaskId(item.getTeachingTaskId());
		assignment.setClassroomId(item.getClassroomId());
		assignment.setTimeSlotId(item.getTimeSlotId());
		assignment.setConsecutiveSlots(null);
		assignment.setStatus(ACTIVE_STATUS);
		return assignment;
	}

	private CourseAssignment toAssignment(Long schemeId, AllocationTemplateSession session) {
		CourseAssignment assignment = new CourseAssignment();
		assignment.setSourceSchemeId(schemeId);
		assignment.setTeachingTaskId(session.getTeachingTaskId());
		assignment.setClassroomId(session.getClassroomId());
		assignment.setTimeSlotId(session.getTimeSlotId());
		assignment.setConsecutiveSlots(session.getConsecutiveSlots());
		assignment.setStatus(ACTIVE_STATUS);
		return assignment;
	}
}
