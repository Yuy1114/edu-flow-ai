package com.yuy.eduflow.dataquality;

import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface DatasetQualitySnapshotMapper {

	@Select("""
		SELECT id, fingerprint, dataset_dir, source_files, occurrence_rows,
		       teaching_sessions, teaching_tasks, duplicates_removed,
		       trainable_tasks, trainable_sessions, joint_tasks, evening_sessions,
		       captured_by, created_at
		FROM dataset_quality_snapshot
		ORDER BY created_at DESC
		LIMIT #{limit}
		""")
	List<DatasetQualitySnapshot> findRecent(int limit);

	@Select("""
		SELECT id, fingerprint, dataset_dir, source_files, occurrence_rows,
		       teaching_sessions, teaching_tasks, duplicates_removed,
		       trainable_tasks, trainable_sessions, joint_tasks, evening_sessions,
		       report_json, captured_by, created_at
		FROM dataset_quality_snapshot
		WHERE fingerprint = #{fingerprint}
		""")
	DatasetQualitySnapshot findByFingerprint(String fingerprint);

	@Insert("""
		INSERT INTO dataset_quality_snapshot
		    (fingerprint, dataset_dir, source_files, occurrence_rows, teaching_sessions,
		     teaching_tasks, duplicates_removed, trainable_tasks, trainable_sessions,
		     joint_tasks, evening_sessions, report_json, captured_by)
		VALUES
		    (#{fingerprint}, #{datasetDir}, #{sourceFiles}, #{occurrenceRows}, #{teachingSessions},
		     #{teachingTasks}, #{duplicatesRemoved}, #{trainableTasks}, #{trainableSessions},
		     #{jointTasks}, #{eveningSessions}, #{reportJson}, #{capturedBy})
		""")
	@Options(useGeneratedKeys = true, keyProperty = "id")
	int insert(DatasetQualitySnapshot snapshot);
}
