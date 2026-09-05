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
public interface AllocationTemplateMapper {

	@Select("""
		SELECT generation_run_id
		FROM schedule_template
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id IS NOT NULL
		  AND status = 'ACTIVE'
		  AND EXISTS (
		      SELECT 1 FROM allocation_scheme s
		      WHERE s.task_id = schedule_template.allocation_task_id
		        AND s.model_version LIKE 'v3.5%'
		        AND s.status IN ('CANDIDATE', 'CONFIRMED')
		        AND JSON_VALID(s.summary)
		        AND JSON_UNQUOTE(JSON_EXTRACT(s.summary, '$.generation_run_id')) = schedule_template.generation_run_id
		  )
		ORDER BY created_at DESC, id DESC
		LIMIT 1
		""")
	String findLatestGenerationRunId(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, generation_run_id, template_code, template_name, template_order,
		       source_type, algorithm_version, status, fragment_count, task_count,
		       created_at, updated_at
		FROM schedule_template
		WHERE allocation_task_id = #{allocationTaskId}
		ORDER BY template_order, id
		""")
	List<AllocationTemplate> findTemplates(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, generation_run_id, template_code, template_name, template_order,
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
		SELECT id, allocation_task_id, generation_run_id, week_number, template_id, template_code,
		       source_type, notes, created_at, updated_at
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		ORDER BY week_number
		""")
	List<AllocationTemplateWeek> findTemplateWeeks(@Param("allocationTaskId") Long allocationTaskId);

	@Select("""
		SELECT id, allocation_task_id, generation_run_id, week_number, template_id, template_code,
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
		SELECT id, allocation_task_id, generation_run_id, week_number, template_id, template_code,
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
		SELECT id, allocation_task_id, generation_run_id, week_number, template_id, template_code,
		       source_type, notes, created_at, updated_at
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		  AND week_number = #{weekNumber}
		""")
	AllocationTemplateWeek findTemplateWeekByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
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
		  AND (
		      EXISTS (SELECT 1 FROM schedule_template_fragment_week fw
		              WHERE fw.template_fragment_id = f.id AND fw.week_number = tw.week_number)
		      OR (NOT EXISTS (SELECT 1 FROM schedule_template_fragment_week fw0
		                      WHERE fw0.template_fragment_id = f.id)
		          AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		              SELECT COUNT(*) FROM schedule_template_week tw2
		              WHERE tw2.template_id = tw.template_id
		                AND tw2.allocation_task_id = tw.allocation_task_id
		                AND tw2.generation_run_id = tw.generation_run_id
		                AND tw2.week_number <= tw.week_number
		          )))
		  )
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
		  AND (
		      EXISTS (SELECT 1 FROM schedule_template_fragment_week fw
		              WHERE fw.template_fragment_id = f.id AND fw.week_number = tw.week_number)
		      OR (NOT EXISTS (SELECT 1 FROM schedule_template_fragment_week fw0
		                      WHERE fw0.template_fragment_id = f.id)
		          AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		              SELECT COUNT(*) FROM schedule_template_week tw2
		              WHERE tw2.template_id = tw.template_id
		                AND tw2.allocation_task_id = tw.allocation_task_id
		                AND tw2.generation_run_id = tw.generation_run_id
		                AND tw2.week_number <= tw.week_number
		          )))
		  )
		ORDER BY s.day_of_week, s.period_index, f.classroom_name, f.class_name, f.course_name
		""")
	List<AllocationTemplateTimetableEntry> findWeekTimetableByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("weekNumber") Integer weekNumber
	);

	@Select("""
		SELECT st.id, st.allocation_task_id, st.generation_run_id, st.template_code,
		       st.template_name, st.template_order, st.source_type, st.algorithm_version,
		       st.status, st.fragment_count, st.task_count, st.created_at, st.updated_at
		FROM schedule_template st
		WHERE st.id = #{templateId}
		  AND st.allocation_task_id = #{allocationTaskId}
		  AND st.generation_run_id = #{generationRunId}
		""")
	AllocationTemplate findTemplateByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("templateId") Long templateId
	);

	@Select("""
		SELECT f.id, f.template_id, f.template_code, f.allocation_task_id, f.generation_run_id,
		       f.fragment_code, f.teaching_task_id, f.source_key, f.course_id, f.course_name,
		       f.teacher_id, f.teacher_name, f.class_group_id, f.class_name,
		       f.classroom_id, f.classroom_name, f.day_of_week, f.period_index,
		       f.consecutive_slots, f.duration_weeks, f.session_hours, f.required_room_type,
		       f.source_type, f.lock_status
		FROM schedule_template_fragment f
		WHERE f.id = #{fragmentId}
		  AND f.allocation_task_id = #{allocationTaskId}
		  AND f.generation_run_id = #{generationRunId}
		""")
	AllocationTemplateFragment findFragmentByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("fragmentId") Long fragmentId
	);

	@Select("""
		SELECT COUNT(*)
		FROM schedule_template_week
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		  AND template_id = #{templateId}
		""")
	int countMappedWeeks(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("templateId") Long templateId
	);

	@Select("""
		SELECT fw.template_fragment_id, fw.week_number
		FROM schedule_template_fragment_week fw
		JOIN schedule_template_fragment f ON f.id = fw.template_fragment_id
		WHERE f.allocation_task_id = #{allocationTaskId}
		  AND f.generation_run_id = #{generationRunId}
		ORDER BY fw.template_fragment_id, fw.week_number
		""")
	List<AllocationTemplateFragmentWeek> findFragmentWeeksByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);

	@Select("""
		SELECT tt.id AS teaching_task_id, c.name AS course_name, tt.total_hours AS required_hours,
		       c.course_type, tt.status AS teaching_task_status, c.status AS course_status,
		       CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2
		            WHEN c.course_type IN ('上机课', '实验课') THEN 4 ELSE 0 END AS session_periods
		FROM allocation_task_teaching_task att
		JOIN teaching_task tt ON tt.id = att.teaching_task_id
		JOIN course c ON c.id = tt.course_id
		WHERE att.allocation_task_id = #{allocationTaskId}
		ORDER BY tt.id
		""")
	List<AllocationTemplateTaskExpectation> findTaskExpectations(
		@Param("allocationTaskId") Long allocationTaskId
	);

	@Select("""
		SELECT COUNT(*) FROM allocation_task_teaching_task
		WHERE allocation_task_id = #{allocationTaskId}
		  AND teaching_task_id = #{teachingTaskId}
		""")
	int countTaskMembership(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("teachingTaskId") Long teachingTaskId
	);

	@Select("""
		SELECT tw.week_number, tw.template_id, tw.template_code,
		       f.id AS template_fragment_id, f.fragment_code, f.teaching_task_id,
		       COALESCE(c.name, f.course_name) AS course_name,
		       COALESCE(
		           NULLIF(CONCAT_WS(',', tt.primary_teacher_id, NULLIF(tt.assistant_teacher_id, tt.primary_teacher_id)), ''),
		           (SELECT GROUP_CONCAT(DISTINCT ft.teacher_id ORDER BY ft.teacher_role DESC, ft.teacher_id SEPARATOR ',' )
		            FROM schedule_template_fragment_teacher ft WHERE ft.template_fragment_id = f.id)
		       ) AS teacher_ids,
		       COALESCE(
		           NULLIF(CONCAT_WS('、', pt.name, CASE WHEN ast.id <> pt.id THEN ast.name END), ''),
		           (SELECT GROUP_CONCAT(DISTINCT t.name ORDER BY ft.teacher_role DESC, t.id SEPARATOR '、')
		            FROM schedule_template_fragment_teacher ft JOIN teacher t ON t.id = ft.teacher_id
		            WHERE ft.template_fragment_id = f.id),
		           f.teacher_name
		       ) AS teacher_name,
		       COALESCE(
		           (SELECT GROUP_CONCAT(ttcg.class_group_id ORDER BY ttcg.class_group_id SEPARATOR ',')
		            FROM teaching_task_class_group ttcg WHERE ttcg.teaching_task_id = f.teaching_task_id),
		           (SELECT GROUP_CONCAT(DISTINCT fc.class_group_id ORDER BY fc.class_group_id SEPARATOR ',')
		            FROM schedule_template_fragment_class_group fc WHERE fc.template_fragment_id = f.id),
		           CAST(f.class_group_id AS CHAR)
		       ) AS class_group_ids,
		       COALESCE(
		           (SELECT GROUP_CONCAT(cg.name ORDER BY cg.id SEPARATOR '、')
		            FROM teaching_task_class_group ttcg JOIN class_group cg ON cg.id = ttcg.class_group_id
		            WHERE ttcg.teaching_task_id = f.teaching_task_id),
		           (SELECT GROUP_CONCAT(DISTINCT cg.name ORDER BY cg.id SEPARATOR '、')
		            FROM schedule_template_fragment_class_group fc JOIN class_group cg ON cg.id = fc.class_group_id
		            WHERE fc.template_fragment_id = f.id),
		           f.class_name
		       ) AS class_name,
		       f.classroom_id, COALESCE(cr.name, f.classroom_name) AS classroom_name,
		       cr.capacity AS classroom_capacity, cr.classroom_type, cr.status AS classroom_status,
		       COALESCE((SELECT SUM(COALESCE(cg.student_count, 0))
		                 FROM teaching_task_class_group ttcg JOIN class_group cg ON cg.id = ttcg.class_group_id
		                 WHERE ttcg.teaching_task_id = f.teaching_task_id), 0) AS student_count,
		       s.day_of_week, s.period_index,
		       f.day_of_week AS start_day_of_week, f.period_index AS start_period_index,
		       f.consecutive_slots, f.duration_weeks, c.course_type,
		       CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2
		            WHEN c.course_type IN ('上机课', '实验课') THEN 4 ELSE 0 END AS expected_session_periods,
		       tt.status AS teaching_task_status, c.status AS course_status,
		       pt.status AS primary_teacher_status,
		       ast.status AS assistant_teacher_status,
		       pp.availability_matrix_json AS primary_availability_matrix_json,
		       ap.availability_matrix_json AS assistant_availability_matrix_json,
		       CASE WHEN
		           (pp.availability_matrix_json IS NOT NULL AND JSON_VALID(pp.availability_matrix_json)
		            AND CAST(JSON_UNQUOTE(JSON_EXTRACT(pp.availability_matrix_json,
		                CONCAT('$[', s.period_index - 1, '][', s.day_of_week - 1, ']'))) AS SIGNED) = -1)
		           OR
		           (ap.availability_matrix_json IS NOT NULL AND JSON_VALID(ap.availability_matrix_json)
		            AND CAST(JSON_UNQUOTE(JSON_EXTRACT(ap.availability_matrix_json,
		                CONCAT('$[', s.period_index - 1, '][', s.day_of_week - 1, ']'))) AS SIGNED) = -1)
		           THEN TRUE ELSE FALSE END AS teacher_hard_unavailable,
		       CASE WHEN tt.classroom_id IS NOT NULL THEN tt.classroom_id = f.classroom_id
		            WHEN EXISTS (SELECT 1 FROM teaching_task_classroom ttc WHERE ttc.teaching_task_id = tt.id)
		            THEN EXISTS (SELECT 1 FROM teaching_task_classroom ttc
		                         WHERE ttc.teaching_task_id = tt.id AND ttc.classroom_id = f.classroom_id)
		            ELSE TRUE END AS classroom_allowed,
		       CASE
		           WHEN tt.id IS NULL OR tt.primary_teacher_id IS NULL THEN FALSE
		           WHEN NOT EXISTS (
		               SELECT 1 FROM schedule_template_fragment_teacher current_primary
		               WHERE current_primary.template_fragment_id = f.id
		                 AND current_primary.teacher_id = tt.primary_teacher_id
		                 AND current_primary.teacher_role = 'PRIMARY'
		           ) THEN FALSE
		           WHEN tt.assistant_teacher_id IS NOT NULL
		             AND tt.assistant_teacher_id <> tt.primary_teacher_id
		             AND NOT EXISTS (
		               SELECT 1 FROM schedule_template_fragment_teacher current_assistant
		               WHERE current_assistant.template_fragment_id = f.id
		                 AND current_assistant.teacher_id = tt.assistant_teacher_id
		                 AND current_assistant.teacher_role = 'ASSISTANT'
		           ) THEN FALSE
		           WHEN EXISTS (
		               SELECT 1 FROM schedule_template_fragment_teacher stale_teacher
		               WHERE stale_teacher.template_fragment_id = f.id
		                 AND NOT (
		                   (stale_teacher.teacher_id = tt.primary_teacher_id AND stale_teacher.teacher_role = 'PRIMARY')
		                   OR (tt.assistant_teacher_id IS NOT NULL
		                       AND tt.assistant_teacher_id <> tt.primary_teacher_id
		                       AND stale_teacher.teacher_id = tt.assistant_teacher_id
		                       AND stale_teacher.teacher_role = 'ASSISTANT')
		                 )
		           ) THEN FALSE
		           ELSE TRUE
		       END AS teacher_relations_current,
		       CASE
		           WHEN NOT EXISTS (
		               SELECT 1 FROM teaching_task_class_group current_class
		               WHERE current_class.teaching_task_id = tt.id
		           ) THEN FALSE
		           WHEN EXISTS (
		               SELECT 1 FROM teaching_task_class_group current_class
		               WHERE current_class.teaching_task_id = tt.id
		                 AND NOT EXISTS (
		                   SELECT 1 FROM schedule_template_fragment_class_group stored_class
		                   WHERE stored_class.template_fragment_id = f.id
		                     AND stored_class.class_group_id = current_class.class_group_id
		                 )
		           ) THEN FALSE
		           WHEN EXISTS (
		               SELECT 1 FROM schedule_template_fragment_class_group stale_class
		               WHERE stale_class.template_fragment_id = f.id
		                 AND NOT EXISTS (
		                   SELECT 1 FROM teaching_task_class_group current_class
		                   WHERE current_class.teaching_task_id = tt.id
		                     AND current_class.class_group_id = stale_class.class_group_id
		                 )
		           ) THEN FALSE
		           ELSE TRUE
		       END AS class_group_relations_current,
		       COALESCE(NULLIF(tt.required_room_type, ''), NULLIF(c.required_room_type, ''), NULLIF(f.required_room_type, '')) AS required_room_type,
		       f.source_type
		FROM schedule_template_week tw
		JOIN schedule_template_fragment f
		  ON f.template_id = tw.template_id
		 AND f.allocation_task_id = tw.allocation_task_id
		 AND f.generation_run_id = tw.generation_run_id
		JOIN schedule_template_fragment_slot s
		  ON s.template_fragment_id = f.id
		 AND s.template_id = f.template_id
		LEFT JOIN teaching_task tt ON tt.id = f.teaching_task_id
		LEFT JOIN course c ON c.id = tt.course_id
		LEFT JOIN teacher pt ON pt.id = tt.primary_teacher_id
		LEFT JOIN teacher ast ON ast.id = tt.assistant_teacher_id
		LEFT JOIN teacher_profile pp ON pp.teacher_id = tt.primary_teacher_id
		LEFT JOIN teacher_profile ap ON ap.teacher_id = tt.assistant_teacher_id
		LEFT JOIN classroom cr ON cr.id = f.classroom_id
		WHERE tw.allocation_task_id = #{allocationTaskId}
		  AND tw.generation_run_id = #{generationRunId}
		  AND (
		      EXISTS (SELECT 1 FROM schedule_template_fragment_week fw
		              WHERE fw.template_fragment_id = f.id AND fw.week_number = tw.week_number)
		      OR (NOT EXISTS (SELECT 1 FROM schedule_template_fragment_week fw0
		                      WHERE fw0.template_fragment_id = f.id)
		          AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		              SELECT COUNT(*) FROM schedule_template_week tw2
		              WHERE tw2.template_id = tw.template_id
		                AND tw2.allocation_task_id = tw.allocation_task_id
		                AND tw2.generation_run_id = tw.generation_run_id
		                AND tw2.week_number <= tw.week_number
		          )))
		  )
		ORDER BY tw.week_number, s.day_of_week, s.period_index, f.id
		""")
	List<AllocationTemplateAuditEntry> findAuditEntriesByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);

	@Select("""
		SELECT tw.week_number, tw.template_id, f.id AS template_fragment_id,
		       f.teaching_task_id, f.classroom_id, f.day_of_week, f.period_index,
		       f.consecutive_slots,
		       ts.id AS time_slot_id
		FROM schedule_template_week tw
		JOIN schedule_template_fragment f
		  ON f.template_id = tw.template_id
		 AND f.allocation_task_id = tw.allocation_task_id
		 AND f.generation_run_id = tw.generation_run_id
		LEFT JOIN time_slot ts
		  ON ts.week_number = tw.week_number
		 AND ts.day_of_week = f.day_of_week
		 AND ts.period_index = f.period_index
		WHERE tw.allocation_task_id = #{allocationTaskId}
		  AND tw.generation_run_id = #{generationRunId}
		  AND (
		      EXISTS (SELECT 1 FROM schedule_template_fragment_week fw
		              WHERE fw.template_fragment_id = f.id AND fw.week_number = tw.week_number)
		      OR (NOT EXISTS (SELECT 1 FROM schedule_template_fragment_week fw0
		                      WHERE fw0.template_fragment_id = f.id)
		          AND (f.duration_weeks IS NULL OR f.duration_weeks >= (
		              SELECT COUNT(*) FROM schedule_template_week tw2
		              WHERE tw2.template_id = tw.template_id
		                AND tw2.allocation_task_id = tw.allocation_task_id
		                AND tw2.generation_run_id = tw.generation_run_id
		                AND tw2.week_number <= tw.week_number
		          )))
		  )
		ORDER BY tw.week_number, f.day_of_week, f.period_index, f.id
		""")
	List<AllocationTemplateSession> findSessionsByRun(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId
	);

	@Select("""
		SELECT id FROM time_slot
		WHERE week_number = #{weekNumber}
		  AND day_of_week = #{dayOfWeek}
		  AND period_index = #{periodIndex}
		LIMIT 1
		""")
	Long findTimeSlotId(
		@Param("weekNumber") Integer weekNumber,
		@Param("dayOfWeek") Integer dayOfWeek,
		@Param("periodIndex") Integer periodIndex
	);

	@Insert("""
		INSERT INTO schedule_template_fragment (
		    template_id, template_code, allocation_task_id, generation_run_id,
		    fragment_code, teaching_task_id, source_key, course_id, course_name,
		    teacher_id, teacher_name, class_group_id, class_name,
		    classroom_id, classroom_name, day_of_week, period_index,
		    consecutive_slots, duration_weeks, session_hours, required_room_type,
		    source_type, lock_status
		) VALUES (
		    #{templateId}, #{templateCode}, #{allocationTaskId}, #{generationRunId},
		    #{fragmentCode}, #{teachingTaskId}, #{sourceKey}, #{courseId}, #{courseName},
		    #{teacherId}, #{teacherName}, #{classGroupId}, #{className},
		    #{classroomId}, #{classroomName}, #{dayOfWeek}, #{periodIndex},
		    #{consecutiveSlots}, #{durationWeeks}, #{sessionHours}, #{requiredRoomType},
		    #{sourceType}, #{lockStatus}
		)
		""")
	@Options(useGeneratedKeys = true, keyProperty = "id")
	int insertFragment(AllocationTemplateFragment fragment);

	@Update("""
		UPDATE schedule_template_fragment
		SET classroom_id = #{classroomId}, classroom_name = #{classroomName},
		    day_of_week = #{dayOfWeek}, period_index = #{periodIndex},
		    consecutive_slots = #{consecutiveSlots}, duration_weeks = #{durationWeeks},
		    session_hours = #{sessionHours}, source_type = 'ADJUSTED'
		WHERE id = #{id}
		""")
	int updateFragmentPlacement(AllocationTemplateFragment fragment);

	@Insert("""
		INSERT INTO schedule_template_fragment_slot (
		    template_fragment_id, fragment_code, template_id, template_code,
		    allocation_task_id, generation_run_id, teaching_task_id,
		    classroom_id, teacher_id, class_group_id, day_of_week, period_index
		) VALUES (
		    #{fragmentId}, #{fragmentCode}, #{templateId}, #{templateCode},
		    #{allocationTaskId}, #{generationRunId}, #{teachingTaskId},
		    #{classroomId}, #{teacherId}, #{classGroupId}, #{dayOfWeek}, #{periodIndex}
		)
		""")
	int insertFragmentSlot(
		@Param("fragmentId") Long fragmentId,
		@Param("fragmentCode") String fragmentCode,
		@Param("templateId") Long templateId,
		@Param("templateCode") String templateCode,
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("teachingTaskId") Long teachingTaskId,
		@Param("classroomId") Long classroomId,
		@Param("teacherId") Long teacherId,
		@Param("classGroupId") Long classGroupId,
		@Param("dayOfWeek") Integer dayOfWeek,
		@Param("periodIndex") Integer periodIndex
	);

	@Insert("""
		INSERT INTO schedule_template_fragment_teacher (
		    template_fragment_id, fragment_code, template_id, template_code,
		    allocation_task_id, generation_run_id, teaching_task_id, teacher_id, teacher_role
		) VALUES (
		    #{fragmentId}, #{fragmentCode}, #{templateId}, #{templateCode},
		    #{allocationTaskId}, #{generationRunId}, #{teachingTaskId}, #{teacherId}, #{teacherRole}
		)
		""")
	int insertFragmentTeacher(
		@Param("fragmentId") Long fragmentId,
		@Param("fragmentCode") String fragmentCode,
		@Param("templateId") Long templateId,
		@Param("templateCode") String templateCode,
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("teachingTaskId") Long teachingTaskId,
		@Param("teacherId") Long teacherId,
		@Param("teacherRole") String teacherRole
	);

	@Insert("""
		INSERT INTO schedule_template_fragment_class_group (
		    template_fragment_id, fragment_code, template_id, template_code,
		    allocation_task_id, generation_run_id, teaching_task_id, class_group_id
		) VALUES (
		    #{fragmentId}, #{fragmentCode}, #{templateId}, #{templateCode},
		    #{allocationTaskId}, #{generationRunId}, #{teachingTaskId}, #{classGroupId}
		)
		""")
	int insertFragmentClassGroup(
		@Param("fragmentId") Long fragmentId,
		@Param("fragmentCode") String fragmentCode,
		@Param("templateId") Long templateId,
		@Param("templateCode") String templateCode,
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("teachingTaskId") Long teachingTaskId,
		@Param("classGroupId") Long classGroupId
	);

	@Insert("""
		INSERT INTO schedule_template_fragment_week (
		    template_fragment_id, allocation_task_id, generation_run_id,
		    template_id, week_number
		) VALUES (
		    #{fragmentId}, #{allocationTaskId}, #{generationRunId},
		    #{templateId}, #{weekNumber}
		)
		""")
	int insertFragmentWeek(
		@Param("fragmentId") Long fragmentId,
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("templateId") Long templateId,
		@Param("weekNumber") Integer weekNumber
	);

	@Delete("DELETE FROM schedule_template_fragment_slot WHERE template_fragment_id = #{fragmentId}")
	int deleteFragmentSlots(@Param("fragmentId") Long fragmentId);

	@Delete("DELETE FROM schedule_template_fragment_teacher WHERE template_fragment_id = #{fragmentId}")
	int deleteFragmentTeachers(@Param("fragmentId") Long fragmentId);

	@Delete("DELETE FROM schedule_template_fragment_class_group WHERE template_fragment_id = #{fragmentId}")
	int deleteFragmentClassGroups(@Param("fragmentId") Long fragmentId);

	@Delete("DELETE FROM schedule_template_fragment_week WHERE template_fragment_id = #{fragmentId}")
	int deleteFragmentWeeks(@Param("fragmentId") Long fragmentId);

	@Delete("DELETE FROM schedule_template_fragment WHERE id = #{fragmentId}")
	int deleteFragment(@Param("fragmentId") Long fragmentId);

	@Update("""
		UPDATE schedule_template
		SET fragment_count = (SELECT COUNT(*) FROM schedule_template_fragment f WHERE f.template_id = #{templateId}),
		    task_count = (SELECT COUNT(DISTINCT f.teaching_task_id) FROM schedule_template_fragment f WHERE f.template_id = #{templateId}),
		    source_type = 'ADJUSTED'
		WHERE id = #{templateId}
		""")
	int refreshTemplateCounts(@Param("templateId") Long templateId);

	@Update("""
		UPDATE schedule_template_week
		SET source_type = 'MANUAL_ADJUSTED'
		WHERE allocation_task_id = #{allocationTaskId}
		  AND generation_run_id = #{generationRunId}
		  AND template_id = #{templateId}
		""")
	int markTemplateWeeksAdjusted(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("generationRunId") String generationRunId,
		@Param("templateId") Long templateId
	);
}
