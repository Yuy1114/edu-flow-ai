package com.yuy.eduflow.assignment;

import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface CourseAssignmentMapper {

	/** Serializes formal timetable publication across different allocation tasks. */
	@Select("SELECT id FROM schedule_publication_lock WHERE id = 1 FOR UPDATE")
	Long lockSchedulePublication();

	@Select("SELECT COUNT(*) FROM course_assignment WHERE status = 'ACTIVE' AND teaching_task_id = #{id}")
	int countActiveByTeachingTask(@Param("id") Long id);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task tt ON tt.id = ca.teaching_task_id
		WHERE ca.status = 'ACTIVE'
		  AND (tt.primary_teacher_id = #{id} OR tt.assistant_teacher_id = #{id})
		""")
	int countActiveByTeacher(@Param("id") Long id);

	@Select("SELECT COUNT(*) FROM course_assignment WHERE status = 'ACTIVE' AND classroom_id = #{id}")
	int countActiveByClassroom(@Param("id") Long id);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task tt ON tt.id = ca.teaching_task_id
		WHERE ca.status = 'ACTIVE' AND tt.course_id = #{id}
		""")
	int countActiveByCourse(@Param("id") Long id);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = ca.teaching_task_id
		WHERE ca.status = 'ACTIVE' AND ttcg.class_group_id = #{id}
		""")
	int countActiveByClassGroup(@Param("id") Long id);

	@Select("""
		<script>
		SELECT tt.id AS teaching_task_id, c.name AS course_name,
		       tt.total_hours AS required_hours,
		       COALESCE(SUM(CASE WHEN ca.status = 'ACTIVE' THEN ca.consecutive_slots ELSE 0 END), 0) AS scheduled_hours,
		       COALESCE(SUM(CASE WHEN ca.status = 'ACTIVE' THEN ca.consecutive_slots ELSE 0 END), 0) - tt.total_hours AS delta_hours,
		       CASE
		         WHEN COALESCE(SUM(CASE WHEN ca.status = 'ACTIVE' THEN ca.consecutive_slots ELSE 0 END), 0) = tt.total_hours THEN 'OK'
		         WHEN COALESCE(SUM(CASE WHEN ca.status = 'ACTIVE' THEN ca.consecutive_slots ELSE 0 END), 0) &lt; tt.total_hours THEN 'UNDER'
		         ELSE 'OVER'
		       END AS status
		FROM teaching_task tt
		JOIN course c ON c.id = tt.course_id
		LEFT JOIN course_assignment ca ON ca.teaching_task_id = tt.id
		WHERE 1 = 1
		<choose>
		  <when test='teachingTaskId != null'>
		    AND tt.id = #{teachingTaskId}
		  </when>
		  <when test='allocationTaskId != null'>
		    AND EXISTS (
		      SELECT 1 FROM allocation_task_teaching_task att
		      WHERE att.allocation_task_id = #{allocationTaskId}
		        AND att.teaching_task_id = tt.id
		    )
		  </when>
		  <otherwise>
		    AND (
		      EXISTS (
		        SELECT 1 FROM course_assignment historical_ca
		        WHERE historical_ca.teaching_task_id = tt.id
		      )
		      OR EXISTS (
		        SELECT 1
		        FROM allocation_task_teaching_task confirmed_att
		        JOIN allocation_scheme confirmed_scheme
		          ON confirmed_scheme.task_id = confirmed_att.allocation_task_id
		         AND confirmed_scheme.status = 'CONFIRMED'
		        WHERE confirmed_att.teaching_task_id = tt.id
		      )
		    )
		  </otherwise>
		</choose>
		GROUP BY tt.id, c.name, tt.total_hours
		ORDER BY tt.id
		</script>
		""")
	List<CourseAssignmentTaskHourAudit> findHourAudit(
		@Param("allocationTaskId") Long allocationTaskId,
		@Param("teachingTaskId") Long teachingTaskId
	);

	List<CourseAssignmentView> findViews(@Param("q") TimetableQuery query);

	List<CourseAssignment> findAll(
		@Param("teacherId") Long teacherId,
		@Param("classGroupId") Long classGroupId,
		@Param("courseId") Long courseId,
		@Param("classroomId") Long classroomId,
		@Param("status") String status,
		@Param("weekNumber") Integer weekNumber
	);

	CourseAssignment findById(Long id);

	@Insert("""
		INSERT INTO course_assignment (
		    source_scheme_id, teaching_task_id,
		    classroom_id, time_slot_id, consecutive_slots, status
		)
		VALUES (
		    #{sourceSchemeId}, #{teachingTaskId},
		    #{classroomId}, #{timeSlotId},
		    COALESCE(#{consecutiveSlots}, (
		        SELECT CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2 ELSE 4 END
		        FROM teaching_task tt JOIN course c ON c.id = tt.course_id
		        WHERE tt.id = #{teachingTaskId}
		    )),
		    #{status}
		)
		""")
	@Options(useGeneratedKeys = true, keyProperty = "id")
	int insert(CourseAssignment assignment);

	@Update("""
		UPDATE course_assignment
		SET classroom_id = #{classroomId},
		    time_slot_id = #{timeSlotId},
		    consecutive_slots = #{consecutiveSlots}
		WHERE id = #{id}
		  AND status = 'ACTIVE'
		""")
	int update(CourseAssignment assignment);

	@Update("""
		UPDATE course_assignment
		SET status = #{status}
		WHERE id = #{id}
		  AND status = 'ACTIVE'
		""")
	int cancel(@Param("id") Long id, @Param("status") String status);

	@Delete("""
		DELETE FROM course_assignment
		WHERE source_scheme_id = #{schemeId}
		""")
	int deleteBySourceSchemeId(@Param("schemeId") Long schemeId);

	@Update("""
		UPDATE course_assignment ca
		JOIN allocation_scheme source_scheme ON source_scheme.id = ca.source_scheme_id
		SET ca.status = #{status}
		WHERE source_scheme.task_id = #{taskId}
		  AND ca.status = 'ACTIVE'
		""")
	int inactivateByAllocationTaskId(@Param("taskId") Long taskId, @Param("status") String status);

	@Update("""
		UPDATE course_assignment
		SET time_slot_id = #{timeSlotId},
		    classroom_id = #{classroomId}
		WHERE id = #{id}
		  AND status = 'ACTIVE'
		""")
	int updateSchedule(
		@Param("id") Long id,
		@Param("timeSlotId") Long timeSlotId,
		@Param("classroomId") Long classroomId
	);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task tt ON ca.teaching_task_id = tt.id
		JOIN course c ON c.id = tt.course_id
		JOIN time_slot ts ON ts.id = ca.time_slot_id
		WHERE ca.status = 'ACTIVE'
		  AND ca.id != #{excludedAssignmentId}
		  AND (tt.primary_teacher_id = #{teacherId} OR tt.assistant_teacher_id = #{teacherId})
		  AND ts.week_number = #{weekNumber}
		  AND ts.day_of_week = #{dayOfWeek}
		  AND ts.period_index <= #{endPeriod}
		  AND ts.period_index + COALESCE(ca.consecutive_slots,
		      CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2 ELSE 4 END) - 1 >= #{startPeriod}
		""")
	int countActiveTeacherTimeConflict(
		@Param("excludedAssignmentId") Long excludedAssignmentId,
		@Param("teacherId") Long teacherId,
		@Param("weekNumber") Integer weekNumber,
		@Param("dayOfWeek") Integer dayOfWeek,
		@Param("startPeriod") Integer startPeriod,
		@Param("endPeriod") Integer endPeriod
	);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = ca.teaching_task_id
		JOIN teaching_task tt ON tt.id = ca.teaching_task_id
		JOIN course c ON c.id = tt.course_id
		JOIN time_slot ts ON ts.id = ca.time_slot_id
		WHERE ca.status = 'ACTIVE'
		  AND ca.id != #{excludedAssignmentId}
		  AND ttcg.class_group_id = #{classGroupId}
		  AND ts.week_number = #{weekNumber}
		  AND ts.day_of_week = #{dayOfWeek}
		  AND ts.period_index <= #{endPeriod}
		  AND ts.period_index + COALESCE(ca.consecutive_slots,
		      CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2 ELSE 4 END) - 1 >= #{startPeriod}
		""")
	int countActiveClassGroupTimeConflict(
		@Param("excludedAssignmentId") Long excludedAssignmentId,
		@Param("classGroupId") Long classGroupId,
		@Param("weekNumber") Integer weekNumber,
		@Param("dayOfWeek") Integer dayOfWeek,
		@Param("startPeriod") Integer startPeriod,
		@Param("endPeriod") Integer endPeriod
	);

	@Select("""
		SELECT COUNT(*)
		FROM course_assignment ca
		JOIN teaching_task tt ON tt.id = ca.teaching_task_id
		JOIN course c ON c.id = tt.course_id
		JOIN time_slot ts ON ts.id = ca.time_slot_id
		WHERE ca.status = 'ACTIVE'
		  AND ca.id != #{excludedAssignmentId}
		  AND ca.classroom_id = #{classroomId}
		  AND ts.week_number = #{weekNumber}
		  AND ts.day_of_week = #{dayOfWeek}
		  AND ts.period_index <= #{endPeriod}
		  AND ts.period_index + COALESCE(ca.consecutive_slots,
		      CASE WHEN c.course_type IN ('理论课', '实践课') THEN 2 ELSE 4 END) - 1 >= #{startPeriod}
		""")
	int countActiveClassroomTimeConflict(
		@Param("excludedAssignmentId") Long excludedAssignmentId,
		@Param("classroomId") Long classroomId,
		@Param("weekNumber") Integer weekNumber,
		@Param("dayOfWeek") Integer dayOfWeek,
		@Param("startPeriod") Integer startPeriod,
		@Param("endPeriod") Integer endPeriod
	);
}
