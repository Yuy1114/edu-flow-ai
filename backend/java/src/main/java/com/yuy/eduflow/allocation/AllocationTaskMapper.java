package com.yuy.eduflow.allocation;

import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface AllocationTaskMapper {

	List<AllocationTask> findAll(@Param("keyword") String keyword, @Param("status") String status);

	@Select("""
		SELECT id, name, status, created_at, updated_at
		FROM allocation_task
		WHERE id = #{id}
		""")
	AllocationTask findById(Long id);

	@Select("""
		SELECT id, name, status, created_at, updated_at
		FROM allocation_task
		WHERE id = #{id}
		FOR UPDATE
		""")
	AllocationTask findByIdForUpdate(Long id);

	@Select("SELECT COUNT(*) FROM allocation_scheme WHERE task_id = #{taskId}")
	int countSchemesByTaskId(@Param("taskId") Long taskId);

	@Insert("""
		INSERT INTO allocation_task (name, status)
		VALUES (#{name}, #{status})
		""")
	@Options(useGeneratedKeys = true, keyProperty = "id")
	int insert(AllocationTask task);

	@Update("""
		UPDATE allocation_task
		SET name = #{name}
		WHERE id = #{id}
		""")
	int update(AllocationTask task);

	@Update("""
		UPDATE allocation_task
		SET status = #{status}
		WHERE id = #{id}
		""")
	int cancel(@Param("id") Long id, @Param("status") String status);

	@Update("""
		UPDATE allocation_task
		SET status = #{status}
		WHERE id = #{id}
		""")
	int updateStatus(@Param("id") Long id, @Param("status") String status);

	@Update("""
		UPDATE allocation_task
		SET status = #{newStatus}
		WHERE id = #{id}
		  AND status = #{expectedStatus}
		""")
	int updateStatusIfCurrent(
		@Param("id") Long id,
		@Param("expectedStatus") String expectedStatus,
		@Param("newStatus") String newStatus
	);

	@Delete("""
		DELETE ar
		FROM adjustment_request ar
		JOIN course_assignment ca ON ca.id = ar.assignment_id
		JOIN allocation_scheme s ON s.id = ca.source_scheme_id
		WHERE s.task_id = #{taskId}
		""")
	int deleteAdjustmentRequestsByTaskId(Long taskId);

	@Delete("""
		DELETE ca
		FROM course_assignment ca
		JOIN allocation_scheme s ON s.id = ca.source_scheme_id
		WHERE s.task_id = #{taskId}
		""")
	int deleteCourseAssignmentsByTaskId(Long taskId);

	@Delete("""
		DELETE c
		FROM conflict_check_result c
		JOIN allocation_item i ON c.biz_type = 'ALLOCATION_ITEM' AND c.biz_id = i.id
		JOIN allocation_scheme s ON s.id = i.scheme_id
		WHERE s.task_id = #{taskId}
		""")
	int deleteConflictsByTaskId(Long taskId);

	@Delete("""
		DELETE l
		FROM allocation_item_adjustment_log l
		JOIN allocation_scheme s ON s.id = l.scheme_id
		WHERE s.task_id = #{taskId}
		""")
	int deleteAdjustmentLogsByTaskId(Long taskId);

	@Delete("""
		DELETE FROM allocation_scheme_feedback
		WHERE task_id = #{taskId}
		""")
	int deleteFeedbackByTaskId(Long taskId);

	@Delete("""
		DELETE i
		FROM allocation_item i
		JOIN allocation_scheme s ON s.id = i.scheme_id
		WHERE s.task_id = #{taskId}
		""")
	int deleteItemsByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_fragment_slot WHERE allocation_task_id = #{taskId}")
	int deleteTemplateFragmentSlotsByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_fragment_teacher WHERE allocation_task_id = #{taskId}")
	int deleteTemplateFragmentTeachersByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_fragment_class_group WHERE allocation_task_id = #{taskId}")
	int deleteTemplateFragmentClassGroupsByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_fragment_week WHERE allocation_task_id = #{taskId}")
	int deleteTemplateFragmentWeeksByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_fragment WHERE allocation_task_id = #{taskId}")
	int deleteTemplateFragmentsByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template_week WHERE allocation_task_id = #{taskId}")
	int deleteTemplateWeeksByTaskId(Long taskId);

	@Delete("DELETE FROM schedule_template WHERE allocation_task_id = #{taskId}")
	int deleteTemplatesByTaskId(Long taskId);

	@Delete("""
		DELETE FROM allocation_scheme
		WHERE task_id = #{taskId}
		""")
	int deleteSchemesByTaskId(Long taskId);

	@Delete("""
		DELETE FROM allocation_task
		WHERE id = #{id}
		""")
	int deleteById(Long id);

	// === 排课任务与教学任务关联 ===
	@Insert("""
		INSERT INTO allocation_task_teaching_task (allocation_task_id, teaching_task_id)
		VALUES (#{allocationTaskId}, #{teachingTaskId})
		""")
	int insertTeachingTask(@Param("allocationTaskId") Long allocationTaskId, @Param("teachingTaskId") Long teachingTaskId);

	@Delete("""
		DELETE FROM allocation_task_teaching_task
		WHERE allocation_task_id = #{allocationTaskId}
		""")
	int deleteTeachingTasks(Long allocationTaskId);

	List<AllocationTaskTeachingTaskResult> findTeachingTasks(Long allocationTaskId);
}
