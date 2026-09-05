package com.yuy.eduflow.ml;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuy.eduflow.allocation.AllocationItemService;
import com.yuy.eduflow.allocation.AllocationItemView;
import com.yuy.eduflow.allocation.AllocationSchemeService;
import com.yuy.eduflow.common.ApiResponse;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.teacher.TeacherProfile;
import com.yuy.eduflow.teacher.TeacherProfileMapper;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ml/teacher-profiles")
public class MlTeacherProfileController {
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final AllocationSchemeService allocationSchemeService;
    private final AllocationItemService allocationItemService;
    private final TeacherProfileMapper teacherProfileMapper;
    private final TeacherProfileFeedbackAggregationService feedbackAggregationService;

    public MlTeacherProfileController(
        AllocationSchemeService allocationSchemeService,
        AllocationItemService allocationItemService,
        TeacherProfileMapper teacherProfileMapper,
        TeacherProfileFeedbackAggregationService feedbackAggregationService
    ) {
        this.allocationSchemeService = allocationSchemeService;
        this.allocationItemService = allocationItemService;
        this.teacherProfileMapper = teacherProfileMapper;
        this.feedbackAggregationService = feedbackAggregationService;
    }

    @GetMapping("/v3")
    public ApiResponse<Map<String, Object>> getV3Profiles() {
        return ApiResponse.success(getProfilesDocument());
    }

    @GetMapping("/v3/satisfaction")
    public ApiResponse<Map<String, Object>> getV3SatisfactionReport(@RequestParam Long schemeId) {
        allocationSchemeService.findById(schemeId);
        List<AllocationItemView> items = allocationItemService.findViewsBySchemeId(schemeId);
        Map<String, Object> profileDoc = getProfilesDocument();
        return ApiResponse.success(buildSatisfactionReport(schemeId, items, profileDoc));
    }

    @GetMapping("/v3/satisfaction/latest")
    public ApiResponse<Map<String, Object>> getLatestV3SatisfactionReport() {
        Path path = latestSatisfactionReportPath();
        return ApiResponse.success(readJsonFile(path, "读取 V3 教师画像满足度报告失败"));
    }

    private Map<String, Object> buildSatisfactionReport(
        Long schemeId,
        List<AllocationItemView> items,
        Map<String, Object> profileDoc
    ) {
        Map<String, Map<String, Object>> profilesByTeacherName = profilesByTeacherName(profileDoc);
        Map<String, List<AllocationItemView>> itemsByTeacher = new LinkedHashMap<>();
        for (AllocationItemView item : items) {
            if (item.getTeacherName() == null || item.getTeacherName().isBlank()) {
                continue;
            }
            itemsByTeacher.computeIfAbsent(item.getTeacherName(), key -> new ArrayList<>()).add(item);
        }

        List<Map<String, Object>> teacherReports = new ArrayList<>();
        for (Map.Entry<String, List<AllocationItemView>> entry : itemsByTeacher.entrySet()) {
            Map<String, Object> profile = profilesByTeacherName.get(entry.getKey());
            if (profile == null) {
                continue;
            }
            teacherReports.add(scoreTeacherItems(profile, entry.getValue()));
        }
        teacherReports.sort(Comparator.comparingDouble(report -> number(report.get("satisfaction_score"))));

        Map<String, Object> schemeReport = new LinkedHashMap<>();
        schemeReport.put("scheme_index", schemeId);
        schemeReport.put("scheme_id", schemeId);
        schemeReport.put("item_count", items.size());
        schemeReport.put("profiled_teacher_count", teacherReports.size());
        schemeReport.put("summary", schemeSummary(teacherReports));
        schemeReport.put("low_satisfaction_teachers", teacherReports.stream().limit(10).toList());
        schemeReport.put("teacher_reports", teacherReports);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("report_version", "v3_teacher_profile_satisfaction_scheme_mvp");
        result.put("generated_at", OffsetDateTime.now().toString());
        result.put("scheme_id", schemeId);
        result.put("profile_version", profileDoc.get("profile_version"));
        result.put("scheme_count", 1);
        result.put("schemes", List.of(schemeReport));
        return result;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Map<String, Object>> profilesByTeacherName(Map<String, Object> profileDoc) {
        Map<String, Map<String, Object>> result = new HashMap<>();
        Object profilesValue = profileDoc.get("profiles");
        if (!(profilesValue instanceof List<?> profiles)) {
            return result;
        }
        for (Object value : profiles) {
            if (!(value instanceof Map<?, ?> rawProfile)) {
                continue;
            }
            Map<String, Object> profile = (Map<String, Object>) rawProfile;
            Object teacherName = profile.get("teacher_name");
            if (teacherName != null) {
                result.put(String.valueOf(teacherName), profile);
            }
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> scoreTeacherItems(Map<String, Object> profile, List<AllocationItemView> items) {
        Map<String, Object> finalProfile = map(profile.get("final_profile"));
        int total = Math.max(1, items.size());
        List<Integer> preferredWeekdays = intList(finalProfile.get("preferred_weekdays"));
        List<Integer> preferredPeriods = intList(finalProfile.get("preferred_periods"));
        int maxDailyLessons = (int) number(finalProfile.get("max_daily_lessons"));

        long earlyCount = items.stream().filter(item -> {
            int period = value(item.getPeriodIndex());
            return period >= SchedulingTimePolicy.FIRST_PERIOD && period <= 2;
        }).count();
        long lateCount = items.stream().filter(item -> SchedulingTimePolicy.isEvening(value(item.getPeriodIndex()))).count();
        long weekdayHits = preferredWeekdays.isEmpty()
            ? total
            : items.stream().filter(item -> preferredWeekdays.contains(value(item.getDayOfWeek()))).count();
        long periodHits = preferredPeriods.isEmpty()
            ? total
            : items.stream().filter(item -> preferredPeriods.contains(value(item.getPeriodIndex()))).count();

        Map<String, Integer> dailyLoads = new HashMap<>();
        for (AllocationItemView item : items) {
            String key = value(item.getWeekNumber()) + "-" + value(item.getDayOfWeek());
            dailyLoads.put(key, dailyLoads.getOrDefault(key, 0) + 1);
        }
        long overloadedDays = dailyLoads.values().stream()
            .filter(load -> maxDailyLessons > 0 && load > maxDailyLessons)
            .count();

        Map<String, Double> components = new LinkedHashMap<>();
        components.put("early_period", bool(finalProfile.get("avoid_early_period")) ? 1.0 - earlyCount / (double) total : 1.0);
        components.put("late_period", bool(finalProfile.get("avoid_late_period")) ? 1.0 - lateCount / (double) total : 1.0);
        components.put("preferred_weekday", preferredWeekdays.isEmpty() ? 1.0 : weekdayHits / (double) total);
        components.put("preferred_period", preferredPeriods.isEmpty() ? 1.0 : periodHits / (double) total);
        components.put("daily_load", dailyLoads.isEmpty() || maxDailyLessons <= 0 ? 1.0 : 1.0 - overloadedDays / (double) dailyLoads.size());
        components.put("room_type", 1.0);
        components.replaceAll((key, value) -> round(clamp(value)));

        double score = components.values().stream().mapToDouble(Double::doubleValue).average().orElse(0.0);

        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("early_item_count", earlyCount);
        evidence.put("late_item_count", lateCount);
        evidence.put("preferred_weekday_hits", weekdayHits);
        evidence.put("preferred_period_hits", periodHits);
        evidence.put("overloaded_days", overloadedDays);
        evidence.put("preferred_room_type_hits", null);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("teacher_id", profile.get("teacher_id"));
        result.put("teacher_name", profile.get("teacher_name"));
        result.put("item_count", items.size());
        result.put("satisfaction_score", round(score));
        result.put("components", components);
        result.put("evidence", evidence);
        result.put("profile_used", finalProfile);
        return result;
    }

    private Map<String, Object> schemeSummary(List<Map<String, Object>> teacherReports) {
        double avg = teacherReports.stream()
            .mapToDouble(report -> number(report.get("satisfaction_score")))
            .average()
            .orElse(0.0);
        long lowCount = teacherReports.stream()
            .filter(report -> number(report.get("satisfaction_score")) < 0.7)
            .count();
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("avg_satisfaction_score", round(avg));
        summary.put("teacher_count", teacherReports.size());
        summary.put("low_satisfaction_count", lowCount);
        summary.put("hard_unavailable_violation_count", 0);
        summary.put("note", "Scheme-level MVP report uses derived soft preferences; room type component is neutral until classroom type is joined.");
        return summary;
    }

    private Map<String, Object> getProfilesDocument() {
        Map<String, Object> doc = readJsonFile(
            "data/profiles/v3/teacher_profiles_v3.json",
            "V3 教师画像文件不存在，请先运行画像生成脚本",
            "读取 V3 教师画像文件失败"
        );
        return mergeFeedbackProfiles(mergeDeclaredProfiles(doc));
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
            TeacherProfile declared = teacherProfileMapper.findByTeacherId(teacherId);
            if (declared == null) {
                continue;
            }
            Map<String, Object> declaredProfile = declaredProfilePayload(declared);
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

    private Path latestSatisfactionReportPath() {
        Path dir = resolveProjectRoot().resolve("data/profiles/v3");
        if (!Files.exists(dir)) {
            throw new ResourceNotFoundException("V3 教师画像满足度报告不存在，请先运行课表满足度分析脚本");
        }
        try (Stream<Path> stream = Files.list(dir)) {
            return stream
                .filter(path -> path.getFileName().toString().endsWith("_teacher_satisfaction_report.json"))
                .max(Comparator.comparingLong(path -> path.toFile().lastModified()))
                .orElseThrow(() -> new ResourceNotFoundException("V3 教师画像满足度报告不存在，请先运行课表满足度分析脚本"));
        } catch (IOException e) {
            throw new IllegalStateException("查找 V3 教师画像满足度报告失败: " + e.getMessage(), e);
        }
    }

    private Map<String, Object> readJsonFile(String relativePath, String notFoundMessage, String readErrorMessage) {
        Path path = resolveProjectRoot().resolve(relativePath);
        if (!Files.exists(path)) {
            throw new ResourceNotFoundException(notFoundMessage);
        }
        return readJsonFile(path, readErrorMessage);
    }

    private Map<String, Object> readJsonFile(Path path, String readErrorMessage) {
        try {
            return objectMapper.readValue(path.toFile(), new TypeReference<>() {});
        } catch (IOException e) {
            throw new IllegalStateException(readErrorMessage + ": " + e.getMessage(), e);
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

    private int value(Integer value) {
        return value == null ? 0 : value;
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

    private double clamp(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }

    private double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }

    private Path resolveProjectRoot() {
        Path current = Path.of(System.getProperty("user.dir")).toAbsolutePath().normalize();
        if (current.getFileName() != null && "server".equals(current.getFileName().toString())) {
            return current.getParent();
        }
        return current;
    }
}
