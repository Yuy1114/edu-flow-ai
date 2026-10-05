package com.yuy.eduflow.allocation;

import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AllocationTeacherSatisfactionMapper {

	@Select("""
		SELECT id, allocation_task_id, generation_run_id, template_code, teacher_key, teacher_id,
		       teacher_name, item_count, days_used, satisfaction_score, preference_score,
		       low_satisfaction, declared_dimensions_json, components_json, evidence_json
		FROM schedule_teacher_satisfaction
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		ORDER BY template_code ASC, preference_score ASC, teacher_name ASC
	""")
	List<AllocationTeacherSatisfaction> findByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);
}
