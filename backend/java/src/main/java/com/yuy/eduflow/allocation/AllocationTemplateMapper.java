package com.yuy.eduflow.allocation;

import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AllocationTemplateMapper {

	@Select("""
		SELECT generation_run_id
		FROM schedule_template
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id IS NOT NULL
		ORDER BY created_at DESC, id DESC
		LIMIT 1
		""")
	String findLatestGenerationRunId(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, template_code, template_name, template_order,
		       source_type, algorithm_version, status, fragment_count, task_count,
		       created_at, updated_at
		FROM schedule_template
		WHERE allocation_task_id = #{allocationTaskId}
		ORDER BY template_order, id
		""")
	List<AllocationTemplate> findTemplates(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, template_code, template_name, template_order,
		       source_type, algorithm_version, status, fragment_count, task_count,
		       created_at, updated_at
		FROM schedule_template
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		ORDER BY template_order, id
		""")
	List<AllocationTemplate> findTemplatesByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);

	@Select("""
		SELECT id, allocation_task_id, week_number, template_id, template_code,
		       source_type, notes, created_at, updated_at
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		ORDER BY week_number
		""")
	List<AllocationTemplateWeek> findTemplateWeeks(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, week_number, template_id, template_code,
		       source_type, notes, created_at, updated_at
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		ORDER BY week_number
		""")
	List<AllocationTemplateWeek> findTemplateWeeksByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);

	@Select("""
		SELECT id, allocation_task_id, week_number, template_id, template_code,
		       source_type, notes, created_at, updated_at
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		  AND week_number = #{weekNumber}
		""")
	AllocationTemplateWeek findTemplateWeek(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("weekNumber") Integer weekNumber
	);

	@Select("""
		SELECT
		    tw.week_number,
		    tw.template_id,
		    tw.template_code,
		    f.id AS template_fragment_id,
		    f.fragment_code,
		    f.teaching_task_id,
		    f.source_key,
		    f.course_id,
		    f.course_name,
		    f.teacher_id,
		    f.teacher_name,
		    f.class_group_id,
		    f.class_name,
		    f.classroom_id,
		    f.classroom_name,
		    s.day_of_week,
		    s.period_index,
		    f.required_room_type,
		    tw.source_type
		FROM schedule_template_week tw
		JOIN schedule_template_fragment_slot s
		  ON s.template_id = tw.template_id
		JOIN schedule_template_fragment f
		  ON f.id = s.template_fragment_id
		WHERE tw.allocation_task_id = #{allocationTaskId}
		  AND tw.week_number = #{weekNumber}
		  AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		      SELECT COUNT(*) FROM schedule_template_week tw2
		      WHERE tw2.template_id = tw.template_id
		        AND tw2.allocation_task_id = tw.allocation_task_id
		        AND tw2.generation_run_id = tw.generation_run_id
		        AND tw2.week_number <= tw.week_number
		  ))
		ORDER BY s.day_of_week, s.period_index, f.classroom_name, f.class_name, f.course_name
		""")
	List<AllocationTemplateTimetableEntry> findWeekTimetable(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("weekNumber") Integer weekNumber
	);

	@Select("""
		SELECT
		    tw.week_number,
		    tw.template_id,
		    tw.template_code,
		    f.id AS template_fragment_id,
		    f.fragment_code,
		    f.teaching_task_id,
		    f.source_key,
		    f.course_id,
		    f.course_name,
		    f.teacher_id,
		    f.teacher_name,
		    f.class_group_id,
		    f.class_name,
		    f.classroom_id,
		    f.classroom_name,
		    s.day_of_week,
		    s.period_index,
		    f.required_room_type,
		    tw.source_type
		FROM schedule_template_week tw
		JOIN schedule_template_fragment_slot s
		  ON s.template_id = tw.template_id
		JOIN schedule_template_fragment f
		  ON f.id = s.template_fragment_id
		WHERE tw.allocation_task_id = #{allocationTaskId}
		  AND tw.generation_run_id = #{generationRunId}
		  AND tw.week_number = #{weekNumber}
		  AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		      SELECT COUNT(*) FROM schedule_template_week tw2
		      WHERE tw2.template_id = tw.template_id
		        AND tw2.allocation_task_id = tw.allocation_task_id
		        AND tw2.generation_run_id = tw.generation_run_id
		        AND tw2.week_number <= tw.week_number
		  ))
		ORDER BY s.day_of_week, s.period_index, f.classroom_name, f.class_name, f.course_name
		""")
	List<AllocationTemplateTimetableEntry> findWeekTimetableByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("weekNumber") Integer weekNumber
	);
}
