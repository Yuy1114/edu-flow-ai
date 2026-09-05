package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.course.Course;
import com.yuy.eduflow.enums.TaskStatus;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AllocationTaskService {
	

	private static final String DEFAULT_ALLOWED_WEEKS = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18";
	private static final String DEFAULT_ALLOWED_WEEKDAYS = "1,2,3,4,5";
	private static final String DEFAULT_ALLOWED_PERIODS = SchedulingTimePolicy.DEFAULT_AUTOMATIC_PERIODS;

	private final AllocationTaskMapper allocationTaskMapper;
	private final AllocationTaskGenerationConfigMapper generationConfigMapper;
	private final ObjectMapper objectMapper = new ObjectMapper();

	public AllocationTaskService(
		AllocationTaskMapper allocationTaskMapper,
		AllocationTaskGenerationConfigMapper generationConfigMapper
	) {
		this.allocationTaskMapper = allocationTaskMapper;
		this.generationConfigMapper = generationConfigMapper;
	}

	public List<AllocationTask> findAll(String keyword, String status) {
		TaskStatus parsedStatus = TaskStatus.from(status);
		List<AllocationTask> tasks = allocationTaskMapper.findAll(
			keyword,
			parsedStatus == null ? null : parsedStatus.code()
		);
		for (AllocationTask task : tasks) {
			task.setTeachingTasks(loadTeachingTasks(task.getId()));
			task.setGenerationConfig(loadGenerationConfig(task.getId()));
		}
		return tasks;
	}

	public AllocationTask findById(Long id) {
		AllocationTask task = allocationTaskMapper.findById(id);
		if (task == null) {
			throw new ResourceNotFoundException("分课任务不存在");
		}
		task.setTeachingTasks(loadTeachingTasks(id));
		task.setGenerationConfig(loadGenerationConfig(id));
		return task;
	}

	private AllocationTaskGenerationConfig loadGenerationConfig(Long taskId) {
		AllocationTaskGenerationConfig config = generationConfigMapper.findByTaskId(taskId);
		return config != null ? config : defaultGenerationConfig(taskId);
	}

	@Transactional
	public AllocationTaskGenerationConfig updateGenerationConfig(Long taskId, AllocationTaskGenerationConfigRequest request) {
		requireMutableTask(taskId);
		AllocationTaskGenerationConfig config = toGenerationConfig(taskId, request);
		AllocationTaskGenerationConfig existing = generationConfigMapper.findByTaskId(taskId);
		if (existing == null) {
			generationConfigMapper.insert(config);
		} else {
			generationConfigMapper.updateByTaskId(config);
		}
		return generationConfigMapper.findByTaskId(taskId);
	}

	private List<TeachingTask> loadTeachingTasks(Long taskId) {
		List<AllocationTaskTeachingTaskResult> results = allocationTaskMapper.findTeachingTasks(taskId);
		return results.stream().map(this::toTeachingTask).collect(Collectors.toList());
	}

	private TeachingTask toTeachingTask(AllocationTaskTeachingTaskResult r) {
		TeachingTask tt = new TeachingTask();
		tt.setId(r.getId());
		tt.setCourseId(r.getCourseId());
		tt.setPrimaryTeacherId(r.getPrimaryTeacherId());
		tt.setAssistantTeacherId(r.getAssistantTeacherId());
		tt.setTotalHours(r.getTotalHours());
		tt.setClassroomId(r.getClassroomId());
		tt.setNotes(r.getNotes());
		tt.setStatus(r.getStatus());
		tt.setCreatedAt(r.getCreatedAt());
		tt.setUpdatedAt(r.getUpdatedAt());

		if (r.getCourseName() != null) {
			Course course = new Course();
			course.setId(r.getCourseId());
			course.setName(r.getCourseName());
			tt.setCourse(course);
		}
		if (r.getPrimaryTeacherName() != null) {
			Teacher teacher = new Teacher();
			teacher.setId(r.getPrimaryTeacherId());
			teacher.setName(r.getPrimaryTeacherName());
			tt.setPrimaryTeacher(teacher);
		}
		if (r.getAssistantTeacherName() != null) {
			Teacher teacher = new Teacher();
			teacher.setId(r.getAssistantTeacherId());
			teacher.setName(r.getAssistantTeacherName());
			tt.setAssistantTeacher(teacher);
		}
		return tt;
	}

    @Transactional
	public AllocationTask create(AllocationTaskRequest request) {
        validateRequest(request);
		AllocationTask task = toTask(new AllocationTask(), request);
		allocationTaskMapper.insert(task);
		if (request.teachingTaskIds() != null) {
			bindTeachingTasks(task.getId(), request.teachingTaskIds());
		}
		saveGenerationConfig(task.getId(), request.generationConfig(), true);
		task.setGenerationConfig(loadGenerationConfig(task.getId()));
		return task;
	}

    @Transactional
	public AllocationTask update(Long id, AllocationTaskRequest request) {
		AllocationTask existing = requireMutableTask(id);
        validateRequest(request);
		AllocationTask task = toTask(existing, request);
		allocationTaskMapper.update(task);
        allocationTaskMapper.deleteTeachingTasks(id);
		if (request.teachingTaskIds() != null) {
			bindTeachingTasks(id, request.teachingTaskIds());
		}
		if (request.generationConfig() != null) {
			saveGenerationConfig(id, request.generationConfig(), false);
		}
		task.setGenerationConfig(loadGenerationConfig(id));
		return task;
	}

    @Transactional
	public void delete(Long id) {
		requireMutableTask(id);
		allocationTaskMapper.deleteAdjustmentRequestsByTaskId(id);
		allocationTaskMapper.deleteCourseAssignmentsByTaskId(id);
		allocationTaskMapper.deleteConflictsByTaskId(id);
		allocationTaskMapper.deleteAdjustmentLogsByTaskId(id);
		allocationTaskMapper.deleteFeedbackByTaskId(id);
		allocationTaskMapper.deleteItemsByTaskId(id);
		allocationTaskMapper.deleteTemplateFragmentSlotsByTaskId(id);
		allocationTaskMapper.deleteTemplateFragmentTeachersByTaskId(id);
		allocationTaskMapper.deleteTemplateFragmentClassGroupsByTaskId(id);
		allocationTaskMapper.deleteTemplateFragmentWeeksByTaskId(id);
		allocationTaskMapper.deleteTemplateFragmentsByTaskId(id);
		allocationTaskMapper.deleteTemplateWeeksByTaskId(id);
		allocationTaskMapper.deleteTemplatesByTaskId(id);
		allocationTaskMapper.deleteSchemesByTaskId(id);
        allocationTaskMapper.deleteTeachingTasks(id);
		allocationTaskMapper.deleteById(id);
	}

    private void bindTeachingTasks(Long taskId, List<Long> teachingTaskIds) {
        for (Long teachingTaskId : teachingTaskIds) {
            if (teachingTaskId != null && teachingTaskId > 0) {
                allocationTaskMapper.insertTeachingTask(taskId, teachingTaskId);
            }
        }
    }

	private void saveGenerationConfig(Long taskId, AllocationTaskGenerationConfigRequest request, boolean createDefaultWhenAbsent) {
		AllocationTaskGenerationConfig config = toGenerationConfig(taskId, request);
		AllocationTaskGenerationConfig existing = generationConfigMapper.findByTaskId(taskId);
		if (existing == null) {
			if (createDefaultWhenAbsent || request != null) {
				generationConfigMapper.insert(config);
			}
			return;
		}
		generationConfigMapper.updateByTaskId(config);
	}

	private AllocationTaskGenerationConfig toGenerationConfig(Long taskId, AllocationTaskGenerationConfigRequest request) {
		AllocationTaskGenerationConfig config = defaultGenerationConfig(taskId);
		if (request == null) {
			return config;
		}
		config.setAllowedWeeks(defaultString(request.allowedWeeks(), DEFAULT_ALLOWED_WEEKS));
		config.setAllowedWeekdays(defaultString(request.allowedWeekdays(), DEFAULT_ALLOWED_WEEKDAYS));
		config.setAllowedPeriods(defaultString(request.allowedPeriods(), DEFAULT_ALLOWED_PERIODS));
		config.setGenerationMode(defaultGenerationMode(request.generationMode()));
		config.setSchemeCount(defaultInteger(request.schemeCount(), 3));
		config.setPlacementTopK(defaultInteger(request.placementTopK(), 80));
		config.setRawPlanCount(defaultInteger(request.rawPlanCount(), 240));
		config.setCpPlanCount(defaultInteger(request.cpPlanCount(), 80));
		config.setSolverTimeLimitSeconds(defaultInteger(request.solverTimeLimitSeconds(), 1800));
		config.setTeacherProfilePenaltyScale(defaultDecimal(request.teacherProfilePenaltyScale(), "50.0000"));
		config.setEarlyPeriodPenalty(defaultDecimal(request.earlyPeriodPenalty(), "0.012000"));
		config.setLatePeriodPenalty(defaultDecimal(request.latePeriodPenalty(), "0.008000"));
		config.setWeekendPenalty(defaultDecimal(request.weekendPenalty(), "0.010000"));
		config.setLlmPrompt(request.llmPrompt());
		config.setLlmResultJson(request.llmResultJson());
		config.setLlmOverrides(request.llmOverrides());
		config.setModelWeight(defaultDecimal(request.modelWeight(), "0.600000"));
		config.setLlmWeight(defaultDecimal(request.llmWeight(), "0.400000"));
		config.setSameDayWeight(defaultDecimal(request.sameDayWeight(), "0.050000"));
		config.setCapacityWastePenalty(defaultDecimal(request.capacityWastePenalty(), "0.000000"));
		config.setTeacherDayLoadPenalty(defaultDecimal(request.teacherDayLoadPenalty(), "0.000000"));
		config.setClassDayLoadPenalty(defaultDecimal(request.classDayLoadPenalty(), "0.000000"));
		config.setTeacherOverloadPenalty(defaultDecimal(request.teacherOverloadPenalty(), "0.000000"));
		return config;
	}

	private AllocationTaskGenerationConfig defaultGenerationConfig(Long taskId) {
		AllocationTaskGenerationConfig config = new AllocationTaskGenerationConfig();
		config.setTaskId(taskId);
		config.setAllowedWeeks(DEFAULT_ALLOWED_WEEKS);
		config.setAllowedWeekdays(DEFAULT_ALLOWED_WEEKDAYS);
		config.setAllowedPeriods(DEFAULT_ALLOWED_PERIODS);
		config.setSchemeCount(3);
		config.setPlacementTopK(80);
		config.setRawPlanCount(240);
		config.setCpPlanCount(80);
		config.setSolverTimeLimitSeconds(1800);
		config.setGenerationMode("AUTO");
		config.setTeacherProfilePenaltyScale(new BigDecimal("80.0000"));
		config.setEarlyPeriodPenalty(new BigDecimal("0.040000"));
		config.setLatePeriodPenalty(new BigDecimal("0.030000"));
		config.setWeekendPenalty(new BigDecimal("0.050000"));
		config.setModelWeight(new BigDecimal("0.600000"));
		config.setLlmWeight(new BigDecimal("0.400000"));
		config.setSameDayWeight(new BigDecimal("0.050000"));
		config.setCapacityWastePenalty(new BigDecimal("0.000000"));
		config.setTeacherDayLoadPenalty(new BigDecimal("0.000000"));
		config.setClassDayLoadPenalty(new BigDecimal("0.000000"));
		config.setTeacherOverloadPenalty(new BigDecimal("0.000000"));
		return config;
	}

	private String defaultString(String value, String defaultValue) {
		return value != null && !value.isBlank() ? value.trim() : defaultValue;
	}

	private Integer defaultInteger(Integer value, Integer defaultValue) {
		return value != null ? value : defaultValue;
	}

	private BigDecimal defaultDecimal(BigDecimal value, String defaultValue) {
		return value != null ? value : new BigDecimal(defaultValue);
	}

	private String defaultGenerationMode(String value) {
		if (value == null || value.isBlank()) {
			return "AUTO";
		}
		String mode = value.trim().toUpperCase();
		return switch (mode) {
			case "AUTO", "AUTO_QUALITY", "AUTO_FULL", "FEASIBILITY", "QUALITY", "STRESS" -> mode;
			default -> "AUTO";
		};
	}

	private AllocationTask toTask(AllocationTask task, AllocationTaskRequest request) {
		task.setName(request.name());
		if (task.getStatus() == null) {
			task.setStatus(TaskStatus.CREATED);
		}
		return task;
	}

    private void validateRequest(AllocationTaskRequest request) {
        if (request.name() == null || request.name().isBlank()) {
            throw new ValidationException("任务名称不能为空");
        }

		validateGenerationConfig(request.generationConfig());
    }

	private void validateGenerationConfig(AllocationTaskGenerationConfigRequest config) {
		if (config == null) {
			return;
		}
		validateCsvNumbers(
			config.allowedWeeks(), "允许周次",
			SchedulingTimePolicy.FIRST_WEEK, SchedulingTimePolicy.LAST_WEEK
		);
		validateCsvNumbers(config.allowedWeekdays(), "允许星期", 1, 7);
		validateCsvNumbers(config.allowedPeriods(), "允许节次", SchedulingTimePolicy.FIRST_PERIOD, SchedulingTimePolicy.LAST_PERIOD);
		if (config.schemeCount() != null && (config.schemeCount() < 1 || config.schemeCount() > 20)) {
			throw new ValidationException("候选方案数量必须在1到20之间");
		}
		validateRange(config.placementTopK(), "Placement TopK", 1, 200);
		validateRange(config.rawPlanCount(), "原始 plan 数量", 1, 500);
		validateRange(config.cpPlanCount(), "CP-SAT plan 数量", 1, 500);
		validateRange(config.solverTimeLimitSeconds(), "CP-SAT 时间上限", 1, 3600);
		if (config.generationMode() != null) {
			String mode = config.generationMode().trim().toUpperCase();
			if (!mode.equals("AUTO") && !mode.equals("AUTO_QUALITY") && !mode.equals("AUTO_FULL") && !mode.equals("FEASIBILITY") && !mode.equals("QUALITY") && !mode.equals("STRESS")) {
				throw new ValidationException("运行模式必须为 AUTO、AUTO_QUALITY、AUTO_FULL、FEASIBILITY、QUALITY 或 STRESS");
			}
		}
	}

	private void validateRange(Integer value, String fieldName, int min, int max) {
		if (value != null && (value < min || value > max)) {
			throw new ValidationException(fieldName + "必须在" + min + "到" + max + "之间");
		}
	}

	private void validateCsvNumbers(String rawValue, String fieldName, int min, int max) {
		if (rawValue == null || rawValue.isBlank()) {
			return;
		}
		String[] parts = rawValue.split(",");
		for (String part : parts) {
			String trimmed = part.trim();
			if (trimmed.isBlank()) {
				throw new ValidationException(fieldName + "不能包含空值");
			}
			try {
				int value = Integer.parseInt(trimmed);
				if (value < min || value > max) {
					throw new ValidationException(fieldName + "必须在" + min + "到" + max + "之间");
				}
			} catch (NumberFormatException exception) {
				throw new ValidationException(fieldName + "必须为逗号分隔的数字");
			}
		}
	}

	// ── LLM Constraint Management ────────────────────────────────────

	public AllocationTaskGenerationConfig getGenerationConfig(Long taskId) {
		AllocationTaskGenerationConfig config = generationConfigMapper.findByTaskId(taskId);
		return config;
	}

	@Transactional
	public void toggleConstraint(Long taskId, String constraintId) {
		requireMutableTask(taskId);
		AllocationTaskGenerationConfig config = generationConfigMapper.findByTaskId(taskId);
		if (config == null || config.getLlmOverrides() == null) return;
		try {
			JsonNode root = objectMapper.readTree(config.getLlmOverrides());
			JsonNode overrides = root.get("overrides");
			if (overrides != null && overrides.isArray()) {
				for (JsonNode node : overrides) {
					JsonNode idNode = node.get("id");
					if (idNode != null && constraintId.equals(idNode.asText())) {
						boolean current = node.has("active") && node.get("active").asBoolean();
						((ObjectNode) node).put("active", !current);
						break;
					}
				}
			}
			config.setLlmOverrides(objectMapper.writeValueAsString(root));
			generationConfigMapper.updateByTaskId(config);
		} catch (JsonProcessingException e) {
			throw new RuntimeException("Failed to parse llmOverrides JSON", e);
		}
	}

	@Transactional
	public void deleteConstraint(Long taskId, String constraintId) {
		requireMutableTask(taskId);
		AllocationTaskGenerationConfig config = generationConfigMapper.findByTaskId(taskId);
		if (config == null || config.getLlmOverrides() == null) return;
		try {
			JsonNode root = objectMapper.readTree(config.getLlmOverrides());
			JsonNode overrides = root.get("overrides");
			if (overrides != null && overrides.isArray()) {
				ArrayNode newOverrides = objectMapper.createArrayNode();
				for (JsonNode node : overrides) {
					JsonNode idNode = node.get("id");
					if (idNode == null || !constraintId.equals(idNode.asText())) {
						newOverrides.add(node);
					}
				}
				((ObjectNode) root).set("overrides", newOverrides);
			}
			config.setLlmOverrides(objectMapper.writeValueAsString(root));
			generationConfigMapper.updateByTaskId(config);
		} catch (JsonProcessingException e) {
			throw new RuntimeException("Failed to parse llmOverrides JSON", e);
		}
	}

	/**
	 * Performs a fail-closed preflight only. Python is the authoritative job
	 * reserver and changes the task to RUNNING in the same transaction as job insert.
	 */
	@Transactional
	public void validateGenerationAllowed(Long taskId) {
		AllocationTask task = allocationTaskMapper.findByIdForUpdate(taskId);
		if (task == null) throw new ResourceNotFoundException("分课任务不存在");
		boolean generatable = task.getStatus() == TaskStatus.CREATED
			|| task.getStatus() == TaskStatus.DRAFT
			|| task.getStatus() == TaskStatus.PENDING
			|| task.getStatus() == TaskStatus.FAILED
			|| task.getStatus() == TaskStatus.BLOCKED;
		if (!generatable || allocationTaskMapper.countSchemesByTaskId(taskId) > 0) {
			throw new ValidationException("排课任务当前不可重新生成；已有候选或已确认任务请新建排课任务");
		}
	}

	private AllocationTask requireMutableTask(Long taskId) {
		AllocationTask task = allocationTaskMapper.findByIdForUpdate(taskId);
		if (task == null) throw new ResourceNotFoundException("分课任务不存在");
		boolean mutableStatus = task.getStatus() == TaskStatus.CREATED
			|| task.getStatus() == TaskStatus.DRAFT
			|| task.getStatus() == TaskStatus.PENDING
			|| task.getStatus() == TaskStatus.FAILED
			|| task.getStatus() == TaskStatus.BLOCKED;
		if (!mutableStatus || allocationTaskMapper.countSchemesByTaskId(taskId) > 0) {
			throw new ValidationException(
				"排课任务已进入生成/复核/发布生命周期，普通修改、删除或重排已禁用；请新建排课任务"
			);
		}
		return task;
	}
}
