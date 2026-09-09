package com.yuy.eduflow.dataquality;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.ml.MlApiClient;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * 训练语料质检。看板载荷由 Python 侧聚合后透传，不在 Java 落库——语料是
 * 训练数据，25 万行 session 进 MySQL 没有意义。只有统计口径会存成快照，
 * 便于清洗规则调整前后做版本对比。
 */
@Service
public class DataQualityService {

	private static final int RECENT_LIMIT = 20;

	private final MlApiClient mlApiClient;
	private final DatasetQualitySnapshotMapper snapshotMapper;
	private final ObjectMapper objectMapper;

	public DataQualityService(
		MlApiClient mlApiClient,
		DatasetQualitySnapshotMapper snapshotMapper,
		ObjectMapper objectMapper
	) {
		this.mlApiClient = mlApiClient;
		this.snapshotMapper = snapshotMapper;
		this.objectMapper = objectMapper;
	}

	public Map<String, Object> board() {
		return mlApiClient.datasetBoard();
	}

	public List<DatasetQualitySnapshot> recentSnapshots() {
		return snapshotMapper.findRecent(RECENT_LIMIT);
	}

	/**
	 * 采集一次快照。指纹取自清洗结果内容，所以同口径重复采集不会新增行——
	 * 直接返回已有那条，避免快照表被无意义的重复记录淹没。
	 */
	public DatasetQualitySnapshot capture(String capturedBy) {
		Map<String, Object> summary = mlApiClient.datasetSummary();
		if (!"ok".equals(summary.get("status"))) {
			throw new ValidationException("数据集不可读：" + summary.get("message"));
		}
		String fingerprint = String.valueOf(summary.get("fingerprint"));
		DatasetQualitySnapshot existing = snapshotMapper.findByFingerprint(fingerprint);
		if (existing != null) {
			return existing;
		}

		@SuppressWarnings("unchecked")
		Map<String, Object> meta = (Map<String, Object>) summary.get("meta");
		@SuppressWarnings("unchecked")
		Map<String, Object> trainable = (Map<String, Object>) meta.get("trainable");

		DatasetQualitySnapshot snapshot = new DatasetQualitySnapshot();
		snapshot.setFingerprint(fingerprint);
		snapshot.setDatasetDir(String.valueOf(summary.getOrDefault("dataset_dir", "")));
		snapshot.setSourceFiles(intOf(meta.get("source_files")));
		snapshot.setOccurrenceRows(intOf(meta.get("occurrence_rows")));
		snapshot.setTeachingSessions(intOf(meta.get("sessions")));
		snapshot.setTeachingTasks(intOf(meta.get("tasks")));
		snapshot.setDuplicatesRemoved(intOf(meta.get("duplicates_removed")));
		snapshot.setTrainableTasks(trainable == null ? 0 : intOf(trainable.get("tasks")));
		snapshot.setTrainableSessions(trainable == null ? 0 : intOf(trainable.get("sessions")));
		snapshot.setJointTasks(trainable == null ? 0 : intOf(trainable.get("joint_tasks")));
		snapshot.setEveningSessions(intOf(meta.get("evening_sessions")));
		snapshot.setCapturedBy(capturedBy);
		snapshot.setReportJson(writeJson(meta));
		snapshotMapper.insert(snapshot);
		// 重新读一次：created_at 由数据库默认值填充，插入对象里还是空的。
		DatasetQualitySnapshot saved = snapshotMapper.findByFingerprint(fingerprint);
		return saved != null ? saved : snapshot;
	}

	private String writeJson(Object value) {
		try {
			return objectMapper.writeValueAsString(value);
		} catch (Exception exception) {
			throw new ValidationException("快照统计口径序列化失败：" + exception.getMessage());
		}
	}

	private static int intOf(Object value) {
		return value instanceof Number number ? number.intValue() : 0;
	}
}
