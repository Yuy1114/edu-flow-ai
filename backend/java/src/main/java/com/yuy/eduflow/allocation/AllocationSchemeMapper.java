package com.yuy.eduflow.allocation;

import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface AllocationSchemeMapper {

	@Select("""
		SELECT COALESCE(MAX(CAST(SUBSTRING(scheme_name, 9) AS SIGNED)), 0)
		FROM allocation_scheme
		WHERE task_id = #{taskId}
		  AND scheme_name LIKE '自训练模型方案 %'
		""")
	int selectMaxSchemeIndex(@Param("taskId") Long taskId);

	@Select("""
		<script>
		SELECT id, task_id, scheme_name, summary, scheme_score,
		       evaluation_summary, model_version,
		       conflict_summary, valid, status, created_at, updated_at
		FROM allocation_scheme
		WHERE 1 = 1
		<if test='taskId != null'>
		  AND task_id = #{taskId}
		</if>
		<if test='status != null and status != ""'>
		  AND status = #{status}
		</if>
		ORDER BY id DESC
		</script>
		""")
	List<AllocationScheme> findAll(@Param("taskId") Long taskId, @Param("status") String status);

	@Select("""
		SELECT id, task_id, scheme_name, summary, scheme_score,
		       evaluation_summary, model_version,
		       conflict_summary, valid, status, created_at, updated_at
		FROM allocation_scheme
		WHERE id = #{id}
		""")
	AllocationScheme findById(Long id);

	@Select("""
		SELECT id, task_id, scheme_name, summary, scheme_score,
		       evaluation_summary, model_version,
		       conflict_summary, valid, status, created_at, updated_at
		FROM allocation_scheme
		WHERE id = #{id}
		FOR UPDATE
		""")
	AllocationScheme findByIdForUpdate(Long id);

	@Insert("""
		INSERT INTO allocation_scheme (
		    task_id, scheme_name, summary, scheme_score,
		    evaluation_summary, model_version,
		    conflict_summary, valid, status
		)
		VALUES (
		    #{taskId}, #{schemeName}, #{summary}, #{schemeScore},
		    #{evaluationSummary}, #{modelVersion},
		    #{conflictSummary}, #{valid}, #{status}
		)
		""")
	@Options(useGeneratedKeys = true, keyProperty = "id")
	int insert(AllocationScheme scheme);

	@Update("""
		UPDATE allocation_scheme
		SET task_id = #{taskId},
		    scheme_name = #{schemeName},
		    summary = #{summary},
		    conflict_summary = #{conflictSummary},
		    valid = #{valid},
		    status = #{status}
		WHERE id = #{id}
		""")
	int update(AllocationScheme scheme);

	@Update("""
		UPDATE allocation_scheme
		SET scheme_name = #{schemeName}
		WHERE id = #{id}
		  AND status = 'CANDIDATE'
		""")
	int updateCandidateName(
		@Param("id") Long id,
		@Param("schemeName") String schemeName
	);

	@Update("""
		UPDATE allocation_scheme
		SET status = #{newStatus}
		WHERE task_id = #{taskId}
		  AND status = #{oldStatus}
		""")
	int rejectCandidatesByTaskId(
		@Param("taskId") Long taskId,
		@Param("oldStatus") String oldStatus,
		@Param("newStatus") String newStatus
	);

	@Update("""
		UPDATE allocation_scheme
		SET status = #{status}
		WHERE id = #{id}
		""")
	int updateStatus(@Param("id") Long id, @Param("status") String status);

	@Update("""
		UPDATE allocation_scheme
		SET status = #{newStatus}
		WHERE id = #{id}
		  AND status = #{expectedStatus}
		""")
	int updateStatusIfCurrent(
		@Param("id") Long id,
		@Param("expectedStatus") String expectedStatus,
		@Param("newStatus") String newStatus
	);

	@Update("""
		UPDATE allocation_scheme
		SET status = #{newStatus}
		WHERE task_id = #{taskId}
		  AND id <> #{confirmedSchemeId}
		  AND status = #{oldStatus}
		""")
	int rejectOtherCandidates(
		@Param("taskId") Long taskId,
		@Param("confirmedSchemeId") Long confirmedSchemeId,
		@Param("oldStatus") String oldStatus,
		@Param("newStatus") String newStatus
	);

	@Update("""
		UPDATE allocation_scheme
		SET status = #{newStatus}
		WHERE task_id = #{taskId}
		  AND id <> #{confirmedSchemeId}
		  AND status IN ('CANDIDATE', 'CONFIRMED')
		""")
	int rejectOtherSelectableSchemes(
		@Param("taskId") Long taskId,
		@Param("confirmedSchemeId") Long confirmedSchemeId,
		@Param("newStatus") String newStatus
	);

	@Update("""
		UPDATE allocation_scheme
		SET valid = #{valid},
		    conflict_summary = #{conflictSummary}
		WHERE id = #{id}
		""")
	int updateConflictState(
		@Param("id") Long id,
		@Param("valid") Boolean valid,
		@Param("conflictSummary") String conflictSummary
	);

	@Update("""
		UPDATE allocation_scheme
		SET scheme_score = #{schemeScore},
		    evaluation_summary = #{evaluationSummary},
		    valid = #{valid},
		    conflict_summary = #{conflictSummary}
		WHERE id = #{id}
		""")
	int updateEvaluationState(
		@Param("id") Long id,
		@Param("schemeScore") Double schemeScore,
		@Param("evaluationSummary") String evaluationSummary,
		@Param("valid") Boolean valid,
		@Param("conflictSummary") String conflictSummary
	);

	@Update("""
		UPDATE allocation_scheme
		SET summary = #{summary},
		    valid = #{valid},
		    conflict_summary = #{conflictSummary}
		WHERE id = #{id}
		  AND status = 'CANDIDATE'
		""")
	int updateTemplateReviewState(
		@Param("id") Long id,
		@Param("summary") String summary,
		@Param("valid") Boolean valid,
		@Param("conflictSummary") String conflictSummary
	);

	@Update("""
		UPDATE allocation_scheme
		SET summary = #{summary}
		WHERE id = #{id}
		  AND status = 'CANDIDATE'
		""")
	int updateTemplateSummaryIfCandidate(
		@Param("id") Long id,
		@Param("summary") String summary
	);
}
