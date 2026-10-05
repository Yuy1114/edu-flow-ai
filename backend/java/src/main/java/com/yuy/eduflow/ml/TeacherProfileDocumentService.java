package com.yuy.eduflow.ml;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuy.eduflow.allocation.AllocationTaskMapper;
import com.yuy.eduflow.allocation.AllocationTaskTeachingTaskResult;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.teacher.TeacherProfile;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;

/**
 * V3 教师画像文档的唯一装配处：历史统计基线 → 教师声明覆盖 → 反馈证据挂载。
 *
 * <p>两条消费者共用这一份口径：
 * <ul>
 *   <li>{@code GET /api/ml/teacher-profiles/v3} 走 {@link #load()}：文件缺失直接报错，
 *       页面需要提示"请先运行画像生成脚本"。</li>
 *   <li>正式排课作业走 {@link #finalProfilesForAllocationTask(Long)}：文件缺失时退化为
 *       "只有教师声明画像"，排课不会因为画像文件不在而停摆——画像只是排序器，读不到就没有偏好。</li>
 * </ul>
 */
@Service
public class TeacherProfileDocumentService {

	static final String PROFILE_DOCUMENT_PATH = "data/profiles/v3/teacher_profiles_v3.json";

	/** 排课引擎认下的软偏好字段；其余键（source、profile_note…）只是说明，不影响排序。 */
	private static final List<String> PREFERENCE_KEYS = List.of(
		"avoid_early_period", "avoid_late_period", "prefer_compact_schedule",
		"preferred_weekdays", "preferred_periods", "max_daily_lessons", "preferred_room_types"
	);

	private final ObjectMapper objectMapper = new ObjectMapper();
	private final TeacherProfileMapper teacherProfileMapper;
	private final TeacherProfileFeedbackAggregationService feedbackAggregationService;
	private final AllocationTaskMapper allocationTaskMapper;

	public TeacherProfileDocumentService(
		TeacherProfileMapper teacherProfileMapper,
		TeacherProfileFeedbackAggregationService feedbackAggregationService,
		AllocationTaskMapper allocationTaskMapper
	) {
		this.teacherProfileMapper = teacherProfileMapper;
		this.feedbackAggregationService = feedbackAggregationService;
		this.allocationTaskMapper = allocationTaskMapper;
	}

	/** 画像文档（基线 + 声明 + 反馈）。文件缺失时报错，供画像接口使用。 */
	public Map<String, Object> load() {
		Path path = projectRoot().resolve(PROFILE_DOCUMENT_PATH);
		if (!Files.exists(path)) {
			throw new ResourceNotFoundException("V3 教师画像文件不存在，请先运行画像生成脚本");
		}
		return loadFrom(path);
	}

	/** 画像文档，文件缺失时返回空文档（排课链路用）。 */
	public Map<String, Object> loadIfPresent() {
		Path path = projectRoot().resolve(PROFILE_DOCUMENT_PATH);
		if (!Files.exists(path)) {
			return new LinkedHashMap<>();
		}
		return loadFrom(path);
	}

	private Map<String, Object> loadFrom(Path path) {
		return mergeFeedbackProfiles(mergeDeclaredProfiles(readJsonObject(path, "读取 V3 教师画像文件失败")));
	}

	/**
	 * 某个排课任务涉及的教师（主讲 + 助理）的 {@code final_profile}，键是教师 ID 字符串。
	 *
	 * <p>只包含确实带着至少一条软偏好的教师：没有偏好的教师不进 payload，Python 侧对这类
	 * 教师保持引擎原有候选顺序（这也是"接入前后逐位相同"能被验证的前提）。
	 */
	public Map<String, Map<String, Object>> finalProfilesForAllocationTask(Long allocationTaskId) {
		Map<Long, Map<String, Object>> byTeacherId = profilesByTeacherId(loadIfPresent());
		Map<String, Map<String, Object>> payload = new LinkedHashMap<>();
		for (Long teacherId : teacherIdsOf(allocationTaskId)) {
			Map<String, Object> baseline = byTeacherId.getOrDefault(teacherId, Map.of());
			Map<String, Object> finalProfile = mergeFinalProfile(
				new LinkedHashMap<>(map(baseline.get("final_profile"))),
				declaredProfilePayload(teacherProfileMapper.findByTeacherId(teacherId))
			);
			// 反馈聚合算出来的偏好节次不进 final_profile（它是证据不是声明），这里补上，
			// 否则镜像侧只有一个"偏好节次"维度永远拿不到值。
			if (!finalProfile.containsKey("preferred_periods") && baseline.get("preferred_periods") != null) {
				finalProfile.put("preferred_periods", baseline.get("preferred_periods"));
			}
			if (!carriesPreference(finalProfile)) {
				continue;
			}
			finalProfile.putIfAbsent("source", "derived_plus_declared");
			payload.put(String.valueOf(teacherId), finalProfile);
		}
		return payload;
	}

	private Set<Long> teacherIdsOf(Long allocationTaskId) {
		Set<Long> teacherIds = new LinkedHashSet<>();
		for (AllocationTaskTeachingTaskResult row : allocationTaskMapper.findTeachingTasks(allocationTaskId)) {
			addTeacherId(teacherIds, row.getPrimaryTeacherId());
			addTeacherId(teacherIds, row.getAssistantTeacherId());
		}
		return teacherIds;
	}

	private void addTeacherId(Set<Long> teacherIds, Long teacherId) {
		if (teacherId != null && teacherId > 0) {
			teacherIds.add(teacherId);
		}
	}

	private Map<Long, Map<String, Object>> profilesByTeacherId(Map<String, Object> doc) {
		Map<Long, Map<String, Object>> byTeacherId = new LinkedHashMap<>();
		Object profilesValue = doc.get("profiles");
		if (!(profilesValue instanceof List<?> profiles)) {
			return byTeacherId;
		}
		for (Object value : profiles) {
			Map<String, Object> profile = map(value);
			long teacherId = (long) number(profile.get("teacher_id"));
			if (teacherId > 0) {
				byTeacherId.put(teacherId, profile);
			}
		}
		return byTeacherId;
	}

	private boolean carriesPreference(Map<String, Object> finalProfile) {
		for (String key : PREFERENCE_KEYS) {
			Object value = finalProfile.get(key);
			if (value instanceof Boolean flag && flag) {
				return true;
			}
			if (value instanceof List<?> list && !list.isEmpty()) {
				return true;
			}
			if (value instanceof Number number && number.doubleValue() > 0) {
				return true;
			}
		}
		return false;
	}

	public Path projectRoot() {
		Path current = Path.of(System.getProperty("user.dir")).toAbsolutePath().normalize();
		if (current.getFileName() != null && "server".equals(current.getFileName().toString())) {
			return current.getParent();
		}
		return current;
	}

	public Map<String, Object> readJsonPath(Path path, String readErrorMessage) {
		return readJsonObject(path, readErrorMessage);
	}

	Map<String, Object> readJsonFile(String relativePath, String notFoundMessage, String readErrorMessage) {
		Path path = projectRoot().resolve(relativePath);
		if (!Files.exists(path)) {
			throw new ResourceNotFoundException(notFoundMessage);
		}
		return readJsonObject(path, readErrorMessage);
	}

	private Map<String, Object> readJsonObject(Path path, String readErrorMessage) {
		try {
			return objectMapper.readValue(path.toFile(), new TypeReference<>() {});
		} catch (IOException e) {
			throw new IllegalStateException(readErrorMessage + ": " + e.getMessage(), e);
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> mergeFeedbackProfiles(Map<String, Object> doc) {
		Object profilesValue = doc.get("profiles");
		if (!(profilesValue instanceof List<?> profiles)) {
			return doc;
		}
		Map<Long, Map<String, Object>> feedbackByTeacher = feedbackAggregationService.aggregateByTeacher();
		int feedbackProfileCount = 0;
		for (Object value : profiles) {
			if (!(value instanceof Map<?, ?> rawProfile)) {
				continue;
			}
			Map<String, Object> profile = (Map<String, Object>) rawProfile;
			long teacherId = (long) number(profile.get("teacher_id"));
			Map<String, Object> feedback = feedbackByTeacher.get(teacherId);
			if (feedback == null || feedback.isEmpty()) {
				continue;
			}
			profile.putAll(feedback);
			feedbackProfileCount += 1;
		}
		doc.put("feedback_profile_count", feedbackProfileCount);
		doc.put("feedback_merge_strategy", "feedback_evidence_attached_without_overriding_declared_profile");
		return doc;
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> mergeDeclaredProfiles(Map<String, Object> doc) {
		Object profilesValue = doc.get("profiles");
		if (!(profilesValue instanceof List<?> profiles)) {
			return doc;
		}
		int declaredCount = 0;
		for (Object value : profiles) {
			if (!(value instanceof Map<?, ?> rawProfile)) {
				continue;
			}
			Map<String, Object> profile = (Map<String, Object>) rawProfile;
			long teacherId = (long) number(profile.get("teacher_id"));
			if (teacherId <= 0) {
				continue;
			}
			Map<String, Object> declaredProfile = declaredProfilePayload(
				teacherProfileMapper.findByTeacherId(teacherId)
			);
			if (declaredProfile.isEmpty()) {
				continue;
			}
			profile.put("declared_profile", declaredProfile);
			profile.put("final_profile", mergeFinalProfile(map(profile.get("final_profile")), declaredProfile));
			declaredCount += 1;
		}
		doc.put("declared_profile_count", declaredCount);
		doc.put("merge_strategy", "teacher_declared_overrides_derived_baseline");
		return doc;
	}

	private Map<String, Object> declaredProfilePayload(TeacherProfile declared) {
		if (declared == null) {
			return Map.of();
		}
		Map<String, Object> payload = new LinkedHashMap<>();
		Map<String, Object> preference = parseJsonObject(declared.getProfilePreferenceJson());
		if (declared.getProfileNote() != null && !declared.getProfileNote().isBlank()) {
			payload.put("profile_note", declared.getProfileNote());
		}
		if (declared.getAvailabilityMatrixJson() != null && !declared.getAvailabilityMatrixJson().isBlank()) {
			payload.put("availability_matrix_json", declared.getAvailabilityMatrixJson());
		}
		if (!preference.isEmpty()) {
			payload.put("preference", preference);
			payload.put("summary", preference.getOrDefault("summary", "教师声明画像已解析"));
		}
		return payload;
	}

	/**
	 * 派生基线 + 教师声明 → 最终画像。字段名是排课引擎与满足度评估共用的那一套。
	 *
	 * <p>已知口径差：声明侧 {@code preferredMaxDailyHours} 是"每天最多几小时"，而
	 * {@code max_daily_lessons} 在评估侧被按"课次"比较。这里沿用既有比较口径，不引入隐式换算；
	 * 要严格化应在声明侧换算（小时 ÷ 每次课时）后再落库。
	 */
	private Map<String, Object> mergeFinalProfile(Map<String, Object> derivedFinal, Map<String, Object> declaredProfile) {
		Map<String, Object> result = new LinkedHashMap<>(derivedFinal);
		Map<String, Object> preference = map(declaredProfile.get("preference"));
		if (preference.isEmpty()) {
			return result;
		}
		if (bool(preference.get("avoidFirstPeriod"))) {
			result.put("avoid_early_period", true);
		}
		if (bool(preference.get("avoidLastPeriod"))) {
			result.put("avoid_late_period", true);
		}
		if (bool(preference.get("preferCompactSchedule"))) {
			result.put("prefer_compact_schedule", true);
		}
		List<Integer> preferredWeekdays = intList(preference.get("preferredWeekdays"));
		if (!preferredWeekdays.isEmpty()) {
			result.put("preferred_weekdays", preferredWeekdays);
		}
		int preferredMaxDaily = (int) number(preference.get("preferredMaxDailyHours"));
		if (preferredMaxDaily > 0) {
			result.put("max_daily_lessons", preferredMaxDaily);
		}
		Object avoidSlots = preference.get("avoidSlots");
		if (avoidSlots instanceof List<?> list && !list.isEmpty()) {
			result.put("declared_avoid_slots", avoidSlots);
		}
		result.put("source", "derived_plus_declared");
		return result;
	}

	private Map<String, Object> parseJsonObject(String json) {
		if (json == null || json.isBlank()) {
			return Map.of();
		}
		try {
			return objectMapper.readValue(json, new TypeReference<>() {});
		} catch (IOException e) {
			return Map.of();
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> map(Object value) {
		if (value instanceof Map<?, ?> raw) {
			return (Map<String, Object>) raw;
		}
		return Map.of();
	}

	private List<Integer> intList(Object value) {
		if (!(value instanceof List<?> list)) {
			return List.of();
		}
		List<Integer> result = new ArrayList<>();
		for (Object item : list) {
			result.add((int) number(item));
		}
		return result;
	}

	private boolean bool(Object value) {
		return Boolean.TRUE.equals(value) || "true".equalsIgnoreCase(String.valueOf(value));
	}

	private double number(Object value) {
		if (value instanceof Number number) {
			return number.doubleValue();
		}
		try {
			return Double.parseDouble(String.valueOf(value));
		} catch (Exception e) {
			return 0.0;
		}
	}
}
