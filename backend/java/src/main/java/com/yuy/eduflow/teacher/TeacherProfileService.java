package com.yuy.eduflow.teacher;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.BusinessException;
import com.yuy.eduflow.llm.OpenAiChatClient;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

@Slf4j
@Service
public class TeacherProfileService {
	private final TeacherService teacherService;
	private final TeacherProfileMapper teacherProfileMapper;
    private final OpenAiChatClient chatClient;
    private final ObjectMapper objectMapper;
	private final FormalScheduleMutationGuard formalScheduleMutationGuard;

	public TeacherProfileService(
		TeacherService teacherService,
        TeacherProfileMapper teacherProfileMapper,
        OpenAiChatClient chatClient,
        ObjectMapper objectMapper,
		FormalScheduleMutationGuard formalScheduleMutationGuard
	) {
		this.teacherService = teacherService;
		this.teacherProfileMapper = teacherProfileMapper;
        this.chatClient = chatClient;
        this.objectMapper = objectMapper;
		this.formalScheduleMutationGuard = formalScheduleMutationGuard;
	}

	public TeacherProfile findByTeacherId(Long teacherId) {
		teacherService.findById(teacherId);
		TeacherProfile profile = teacherProfileMapper.findByTeacherId(teacherId);
		if (profile != null) {
			profile.setAvailabilityMatrixJson(AvailabilityMatrixPolicy.normalize(objectMapper, profile.getAvailabilityMatrixJson()));
		}
		return profile;
	}

    public TeacherProfileParseResult parseProfile(Long teacherId, TeacherProfileParseRequest request) {
        Teacher teacher = teacherService.findById(teacherId);
        String profileNote = clean(request.profileNote());
        if (!StringUtils.hasText(profileNote)) {
            throw new BusinessException(400, "其他说明不能为空，写点人话我才好解析嘛");
        }
        String systemPrompt = """
            你是教务排课系统中的教师画像解析器。请把教师自然语言排课说明解析成 JSON。
            固定周可用性矩阵已经由系统结构化维护，不需要你解析为硬约束。
            你只能输出 JSON object，不要输出 markdown。
            所有从自然语言得到的偏好默认都是软约束，不要把它们标记成硬约束。
            如果教师表达“不能排某时间”，请放入 avoidSlots，并在 warnings 中提醒需要回填到矩阵确认后才会成为硬约束。
            输出字段：preferredMaxWeeklyHours, preferredMaxDailyHours, preferredMaxConsecutiveHours,
            avoidFirstPeriod, avoidLastPeriod, preferCompactSchedule, preferredWeekdays, avoidSlots,
            courseTypePreferences, summary, warnings。
            unavailableSlots 不允许输出，硬不可用只来自 availabilityMatrix 中的 -1。
            """;
        String userPrompt = """
            教师：%s
            固定周矩阵 JSON：%s
            其他说明：%s
            """.formatted(teacher.getName(), AvailabilityMatrixPolicy.normalize(objectMapper, request.availabilityMatrixJson()), profileNote);
        try {
            String raw = chatClient.generate(systemPrompt, userPrompt);
            @SuppressWarnings("unchecked")
            Map<String, Object> parsed = objectMapper.readValue(raw, Map.class);
            Map<String, Object> normalized = normalizeParsedPreference(parsed);
            String preferenceJson = objectMapper.writeValueAsString(normalized);
            String interpretation = String.valueOf(normalized.getOrDefault("summary", "已解析教师排课偏好"));
            return new TeacherProfileParseResult(preferenceJson, normalized, interpretation);
        } catch (Exception e) {
            log.error("Teacher profile parse failed: teacherId={}", teacherId, e);
            throw new BusinessException(500, "教师画像解析失败: " + e.getMessage(), e);
        }
    }

	@Transactional
	public TeacherProfile save(Long teacherId, TeacherProfileRequest request) {
        if (StringUtils.hasText(request.profileNote()) && !StringUtils.hasText(request.profilePreferenceJson())) {
            throw new BusinessException(400, "请先通过 LLM 解析并确认其他说明，再保存教师画像");
        }
		log.info("=== save() start === teacherId={}", teacherId);
		log.info("request={}", request);
		Teacher teacher = teacherService.findById(teacherId);
		formalScheduleMutationGuard.lockAndRejectTeacher(teacherId);
		log.info("teacher found: id={}, name={}", teacher.getId(), teacher.getName());
		TeacherProfile profile = toProfile(teacher, request);
		TeacherProfile existing = teacherProfileMapper.findByTeacherId(teacherId);
		log.info("existing profile: {}", existing);
		if (existing == null) {
			int rows = teacherProfileMapper.insert(profile);
			log.info("INSERT affected rows={}, generated id={}", rows, profile.getId());
		} else {
			int rows = teacherProfileMapper.updateByTeacherId(profile);
			log.info("UPDATE affected rows={}", rows);
		}
        TeacherProfile result = teacherProfileMapper.findByTeacherId(teacherId);
		log.info("=== save() end === profile={}", result);
		return result;
	}

    private TeacherProfile toProfile(Teacher teacher, TeacherProfileRequest request) {
        TeacherProfile profile = new TeacherProfile();
        profile.setTeacherId(teacher.getId());
        profile.setAvailabilityMatrixJson(AvailabilityMatrixPolicy.normalize(objectMapper, request.availabilityMatrixJson()));
        profile.setProfileNote(clean(request.profileNote()));
        profile.setProfilePreferenceJson(clean(request.profilePreferenceJson()));
        return profile;
    }

    private Map<String, Object> normalizeParsedPreference(Map<String, Object> parsed) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("preferredMaxWeeklyHours", parsed.get("preferredMaxWeeklyHours"));
        result.put("preferredMaxDailyHours", parsed.get("preferredMaxDailyHours"));
        result.put("preferredMaxConsecutiveHours", parsed.get("preferredMaxConsecutiveHours"));
        result.put("avoidFirstPeriod", parsed.getOrDefault("avoidFirstPeriod", false));
        result.put("avoidLastPeriod", parsed.getOrDefault("avoidLastPeriod", false));
        result.put("preferCompactSchedule", parsed.getOrDefault("preferCompactSchedule", false));
        result.put("preferredWeekdays", parsed.getOrDefault("preferredWeekdays", List.of()));
        result.put("avoidSlots", parsed.getOrDefault("avoidSlots", List.of()));
        result.put("courseTypePreferences", parsed.getOrDefault("courseTypePreferences", List.of()));
        result.put("summary", parsed.getOrDefault("summary", "已解析教师排课偏好"));
        result.put("warnings", parsed.getOrDefault("warnings", List.of()));
        return result;
    }

	private String clean(String value) {
		return StringUtils.hasText(value) ? value.trim() : null;
	}
}
