package com.yuy.eduflow.teacher;

import com.yuy.eduflow.common.exception.BusinessException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Slf4j
@Service
public class TeacherProfileSnapshotService {

	private static final DateTimeFormatter FILE_TS = DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSS");

	private final TeacherProfileMapper teacherProfileMapper;
	private final ObjectMapper objectMapper;

	public TeacherProfileSnapshotService(
		TeacherProfileMapper teacherProfileMapper,
		ObjectMapper objectMapper
	) {
		this.teacherProfileMapper = teacherProfileMapper;
		this.objectMapper = objectMapper;
	}

	public Path exportForAllocationTask(Long taskId) {
		List<TeacherProfile> profiles = teacherProfileMapper.findByAllocationTaskId(taskId);
		if (profiles.isEmpty()) {
			log.warn("教师画像为空，将不使用教师画像约束：taskId={}", taskId);
			return null;
		}
		
		Path root;
		try {
			root = resolveProjectRoot();
		} catch (BusinessException e) {
			log.warn("无法定位项目根目录，跳过教师画像快照导出：taskId={}", taskId);
			return null;
		}
		
		Path path = root.resolve("ml").resolve("data").resolve("profiles")
			.resolve("snapshots")
			.resolve("task_" + taskId + "_" + LocalDateTime.now().format(FILE_TS) + ".teacher_profiles.jsonl");

		try {
			Files.createDirectories(path.getParent());
			List<String> lines = new ArrayList<>();
			for (TeacherProfile profile : profiles) {
				lines.add(objectMapper.writeValueAsString(toJsonlRow(profile)));
			}
			Files.write(path, lines, StandardCharsets.UTF_8);
			log.info("Teacher profile snapshot exported: taskId={}, profileCount={}, path={}",
				taskId, profiles.size(), path);
			return path;
		} catch (IOException exception) {
			log.warn("导出教师画像快照失败，将不使用教师画像约束：taskId={}", taskId);
			return null;
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> toJsonlRow(TeacherProfile profile) throws IOException {
		Map<String, Object> row = new LinkedHashMap<>();
		row.put("teacher_id", profile.getTeacherId());
		row.put("version", "v1");
		row.put("parser_version", "teacher_profile_service_v1");
		row.put("updated_at", profile.getUpdatedAt());
		row.put("raw_text", profile.getProfileNote());
		row.put("availability_matrix_json", AvailabilityMatrixPolicy.normalize(objectMapper, profile.getAvailabilityMatrixJson()));

		Map<String, Object> profileJson = Map.of();
		if (profile.getProfilePreferenceJson() != null && !profile.getProfilePreferenceJson().isBlank()) {
			profileJson = objectMapper.readValue(profile.getProfilePreferenceJson(), Map.class);
		}
		row.put("profile", profileJson);
		return row;
	}

	private Path resolveProjectRoot() {
		Path cwd = Path.of("").toAbsolutePath().normalize();
		if (Files.isDirectory(cwd.resolve("ml").resolve("scripts"))) {
			return cwd;
		}
		Path parent = cwd.resolve("..").normalize();
		if (Files.isDirectory(parent.resolve("ml").resolve("scripts"))) {
			return parent;
		}
		throw new BusinessException(500, "未找到项目根目录，无法导出教师画像快照");
	}
}
