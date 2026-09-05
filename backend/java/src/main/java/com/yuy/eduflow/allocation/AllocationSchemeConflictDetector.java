package com.yuy.eduflow.allocation;

import com.yuy.eduflow.classroom.Classroom;
import com.yuy.eduflow.classroom.ClassroomMapper;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teacher.Teacher;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class AllocationSchemeConflictDetector {
	static final String TEACHER_TIME = "TEACHER_TIME";
	static final String CLASS_GROUP_TIME = "CLASS_GROUP_TIME";
	static final String CLASSROOM_TIME = "CLASSROOM_TIME";
	static final String CLASSROOM_CAPACITY = "CLASSROOM_CAPACITY";
	static final String CLASSROOM_TYPE = "CLASSROOM_TYPE";
	static final String INVALID_REFERENCE = "INVALID_REFERENCE";
	static final String INVALID_TIME_BLOCK = "INVALID_TIME_BLOCK";
	static final String DUPLICATE_TASK_TIME = "DUPLICATE_TASK_TIME";
	static final String TEACHER_WORKLOAD = "TEACHER_WORKLOAD";
	static final String TEACHING_TASK_HOURS = "TEACHING_TASK_HOURS";

	private final AllocationItemMapper allocationItemMapper;
	private final AllocationTaskMapper allocationTaskMapper;
	private final com.yuy.eduflow.teachingtask.TeachingTaskMapper teachingTaskMapper;
	private final ClassroomMapper classroomMapper;
	private final TimeSlotService timeSlotService;

	public AllocationSchemeConflictDetector(
		AllocationItemMapper allocationItemMapper,
		AllocationTaskMapper allocationTaskMapper,
		com.yuy.eduflow.teachingtask.TeachingTaskMapper teachingTaskMapper,
		ClassroomMapper classroomMapper,
		TimeSlotService timeSlotService
	) {
		this.allocationItemMapper = allocationItemMapper;
		this.allocationTaskMapper = allocationTaskMapper;
		this.teachingTaskMapper = teachingTaskMapper;
		this.classroomMapper = classroomMapper;
		this.timeSlotService = timeSlotService;
	}

	public List<AllocationConflictViolation> detect(List<AllocationItem> items) {
		return detect(items, null);
	}

	public List<AllocationConflictViolation> detect(List<AllocationItem> items, Long allocationTaskId) {
		long startedAt = System.nanoTime();
		if ((items == null || items.isEmpty()) && allocationTaskId == null) {
			return List.of();
		}
		List<AllocationItem> safeItems = items == null ? List.of() : items;
		// 预加载所有教学任务 + 时间段
		long preloadStartedAt = System.nanoTime();
		Set<Long> expectedTaskIds = new LinkedHashSet<>();
		Map<Long, TeachingTaskDetail> taskDetails = loadTaskDetails(safeItems, allocationTaskId, expectedTaskIds);
		Map<Long, Classroom> classroomMap = loadClassrooms(safeItems);
		TimeSlotCatalog timeSlots = loadTimeSlots();
		log.info("Conflict detector preload: items={} allocationTaskId={} expectedTasks={} taskDetails={} classrooms={} timeSlots={} elapsedMs={}",
			safeItems.size(), allocationTaskId, expectedTaskIds.size(), taskDetails.size(), classroomMap.size(), timeSlots.byId().size(), elapsedMs(preloadStartedAt));
		List<AllocationConflictViolation> violations = new ArrayList<>();

		long referenceStartedAt = System.nanoTime();
		int referenceViolations = detectInvalidReferences(safeItems, allocationTaskId, expectedTaskIds, taskDetails, classroomMap, timeSlots, violations);
		log.info("Conflict detector references: violations={} elapsedMs={}", referenceViolations, elapsedMs(referenceStartedAt));
		long timeBlockStartedAt = System.nanoTime();
		int timeBlockViolations = detectInvalidTimeBlocks(safeItems, taskDetails, timeSlots, violations);
		log.info("Conflict detector time-blocks: violations={} elapsedMs={}", timeBlockViolations, elapsedMs(timeBlockStartedAt));
		long duplicateTaskStartedAt = System.nanoTime();
		int duplicateTaskViolations = detectDuplicateTaskTimeViolations(safeItems, taskDetails, timeSlots, violations);
		log.info("Conflict detector duplicate-task-time: violations={} elapsedMs={}", duplicateTaskViolations, elapsedMs(duplicateTaskStartedAt));
		long teacherStartedAt = System.nanoTime();
		int teacherViolations = detectConflicts(
			safeItems,
			item -> teacherKeys(item, taskDetails, timeSlots),
			(item, group, key) -> teacherViolation(item, group, key, taskDetails),
			violations
		);
		log.info("Conflict detector teacher-time: violations={} elapsedMs={}", teacherViolations, elapsedMs(teacherStartedAt));
		long classStartedAt = System.nanoTime();
		int classViolations = detectClassGroupConflicts(safeItems, taskDetails, timeSlots, violations);
		log.info("Conflict detector class-time: violations={} elapsedMs={}", classViolations, elapsedMs(classStartedAt));
		long classroomStartedAt = System.nanoTime();
		int classroomViolations = detectConflicts(
			safeItems,
			item -> classroomKeys(item, taskDetails, timeSlots),
			this::classroomViolation,
			violations
		);
		log.info("Conflict detector classroom-time: violations={} elapsedMs={}", classroomViolations, elapsedMs(classroomStartedAt));
		long roomCapacityStartedAt = System.nanoTime();
		int roomCapacityViolations = detectClassroomCapacityViolations(safeItems, taskDetails, classroomMap, violations);
		log.info("Conflict detector classroom-capacity: violations={} elapsedMs={}", roomCapacityViolations, elapsedMs(roomCapacityStartedAt));
		long roomTypeStartedAt = System.nanoTime();
		int roomTypeViolations = detectClassroomTypeViolations(safeItems, taskDetails, classroomMap, violations);
		log.info("Conflict detector classroom-type: violations={} elapsedMs={}", roomTypeViolations, elapsedMs(roomTypeStartedAt));
		long workloadStartedAt = System.nanoTime();
		int workloadViolations = detectWorkloadViolations(safeItems, taskDetails, violations);
		log.info("Conflict detector workload: violations={} elapsedMs={}", workloadViolations, elapsedMs(workloadStartedAt));
		long hoursStartedAt = System.nanoTime();
		int hourViolations = detectTeachingTaskHourViolations(safeItems, taskDetails, violations);
		log.info("Conflict detector task-hours: violations={} elapsedMs={}", hourViolations, elapsedMs(hoursStartedAt));
		log.info(
			"Conflict detector done: items={} taskDetails={} totalViolations={} elapsedMs={} breakdown={reference:{},timeBlock:{},duplicateTask:{},teacher:{},class:{},classroom:{},capacity:{},type:{},workload:{},hours:{}}",
			safeItems.size(), taskDetails.size(), violations.size(), elapsedMs(startedAt),
			referenceViolations, timeBlockViolations, duplicateTaskViolations, teacherViolations, classViolations, classroomViolations,
			roomCapacityViolations, roomTypeViolations, workloadViolations, hourViolations
		);

		return violations;
	}

	public String summarize(List<AllocationConflictViolation> violations) {
		if (violations == null || violations.isEmpty()) {
			return "无明显冲突";
		}
		Map<String, Long> counts = violations.stream()
			.collect(Collectors.groupingBy(
				AllocationConflictViolation::conflictType,
				LinkedHashMap::new,
				Collectors.counting()
			));
		List<String> parts = new ArrayList<>();
		appendSummary(parts, counts, TEACHER_TIME, "教师时间冲突");
		appendSummary(parts, counts, CLASS_GROUP_TIME, "班级时间冲突");
		appendSummary(parts, counts, CLASSROOM_TIME, "教室时间冲突");
		appendSummary(parts, counts, CLASSROOM_CAPACITY, "教室容量不足");
		appendSummary(parts, counts, CLASSROOM_TYPE, "教室类型不匹配");
		appendSummary(parts, counts, INVALID_REFERENCE, "无效资源引用");
		appendSummary(parts, counts, INVALID_TIME_BLOCK, "非法连排时间块");
		appendSummary(parts, counts, DUPLICATE_TASK_TIME, "教学任务重复时间片");
		appendSummary(parts, counts, TEACHER_WORKLOAD, "教师工作量冲突");
		appendSummary(parts, counts, TEACHING_TASK_HOURS, "教学任务课时不匹配");
		return "发现 " + violations.size() + " 条冲突记录：" + String.join("，", parts);
	}

	private Map<Long, TeachingTaskDetail> loadTaskDetails(List<AllocationItem> items, Long allocationTaskId, Set<Long> expectedTaskIds) {
		Map<Long, TeachingTaskDetail> details = new LinkedHashMap<>();
		if (allocationTaskId != null) {
			for (AllocationTaskTeachingTaskResult taskResult : allocationTaskMapper.findTeachingTasks(allocationTaskId)) {
				if (taskResult.getId() != null) {
					expectedTaskIds.add(taskResult.getId());
				}
				loadTaskDetail(taskResult.getId(), details);
			}
		}
		for (AllocationItem item : items) {
			loadTaskDetail(item.getTeachingTaskId(), details);
		}
		return details;
	}

	private void loadTaskDetail(Long taskId, Map<Long, TeachingTaskDetail> details) {
		if (taskId == null || details.containsKey(taskId)) return;
		var task = teachingTaskMapper.findWithDetails(taskId);
		if (task == null) return;
		int totalStudents = task.getClassGroups() == null ? 0
			: task.getClassGroups().stream().mapToInt(cg -> cg.getStudentCount() != null ? cg.getStudentCount() : 0).sum();
		details.put(taskId, new TeachingTaskDetail(task, totalStudents));
	}

	private TimeSlotCatalog loadTimeSlots() {
		Map<Long, TimeSlot> byId = new LinkedHashMap<>();
		Map<TimeCoordinate, Long> idByCoordinate = new LinkedHashMap<>();
		for (TimeSlot slot : timeSlotService.findAll(null, null)) {
			if (slot.getId() == null) continue;
			byId.put(slot.getId(), slot);
			if (slot.getWeekNumber() != null && slot.getDayOfWeek() != null && slot.getPeriodIndex() != null) {
				idByCoordinate.put(
					new TimeCoordinate(slot.getWeekNumber(), slot.getDayOfWeek(), slot.getPeriodIndex()),
					slot.getId()
				);
			}
		}
		return new TimeSlotCatalog(byId, idByCoordinate);
	}

	private Map<Long, Classroom> loadClassrooms(List<AllocationItem> items) {
		Map<Long, Classroom> classrooms = new LinkedHashMap<>();
		for (AllocationItem item : items) {
			Long classroomId = item.getClassroomId();
			if (classroomId == null || classrooms.containsKey(classroomId)) continue;
			Classroom classroom = classroomMapper.findById(classroomId);
			if (classroom != null) {
				classrooms.put(classroomId, classroom);
			}
		}
		return classrooms;
	}

	private int detectInvalidReferences(
		List<AllocationItem> items,
		Long allocationTaskId,
		Set<Long> expectedTaskIds,
		Map<Long, TeachingTaskDetail> taskDetails,
		Map<Long, Classroom> classroomMap,
		TimeSlotCatalog timeSlots,
		List<AllocationConflictViolation> violations
	) {
		int before = violations.size();
		for (AllocationItem item : items) {
			if (item.getTeachingTaskId() == null) {
				violations.add(invalidReferenceViolation(item, "教学任务为空"));
			} else if (!taskDetails.containsKey(item.getTeachingTaskId())) {
				violations.add(invalidReferenceViolation(item, "教学任务不存在"));
			} else if (allocationTaskId != null && !expectedTaskIds.contains(item.getTeachingTaskId())) {
				violations.add(invalidReferenceViolation(item, "教学任务未绑定到当前排课任务"));
			}
			if (item.getTimeSlotId() == null || !timeSlots.byId().containsKey(item.getTimeSlotId())) {
				violations.add(invalidReferenceViolation(item, "时间段不存在"));
			}
			if (item.getClassroomId() == null || !classroomMap.containsKey(item.getClassroomId())) {
				violations.add(invalidReferenceViolation(item, "教室不存在"));
			}
		}
		return violations.size() - before;
	}

	private int detectInvalidTimeBlocks(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots,
		List<AllocationConflictViolation> violations
	) {
		int before = violations.size();
		for (AllocationItem item : items) {
			TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
			TimeSlot startSlot = timeSlots.byId().get(item.getTimeSlotId());
			if (detail == null || startSlot == null || startSlot.getPeriodIndex() == null) continue;
			String courseType = courseType(detail);
			int periodCount = TeachingSessionTimePolicy.periodCount(courseType);
			if (periodCount == 0) {
				violations.add(invalidTimeBlockViolation(
					item,
					"课程类型缺失或不支持，无法确定一次课占用2节还是4节"
				));
				continue;
			}
			if (!TeachingSessionTimePolicy.isLegalStartPeriod(startSlot.getPeriodIndex(), periodCount)) {
				violations.add(invalidTimeBlockViolation(
					item,
					courseType + "占连续" + periodCount + "节，起始节次只能是"
						+ TeachingSessionTimePolicy.legalStartDescription(periodCount)
						+ "，当前为第" + startSlot.getPeriodIndex() + "节"
				));
				continue;
			}
			for (int period : TeachingSessionTimePolicy.occupiedPeriods(startSlot.getPeriodIndex(), periodCount)) {
				TimeCoordinate coordinate = new TimeCoordinate(startSlot.getWeekNumber(), startSlot.getDayOfWeek(), period);
				if (!timeSlots.idByCoordinate().containsKey(coordinate)) {
					violations.add(invalidTimeBlockViolation(
						item,
						"时间片目录不完整，连续占用所需的第" + period + "节不存在"
					));
					break;
				}
			}
		}
		return violations.size() - before;
	}

	private int detectDuplicateTaskTimeViolations(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots,
		List<AllocationConflictViolation> violations
	) {
		return detectConflicts(
			items,
			item -> resourceKeys(item.getTeachingTaskId(), occupiedCoordinates(item, taskDetails, timeSlots)),
			(item, group, key) -> duplicateTaskTimeViolation(item, group, key, taskDetails),
			violations
		);
	}

	private int detectClassroomCapacityViolations(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		Map<Long, Classroom> classroomMap,
		List<AllocationConflictViolation> violations
	) {
		int before = violations.size();
		for (AllocationItem item : items) {
			TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
			Classroom classroom = classroomMap.get(item.getClassroomId());
			if (detail == null || classroom == null || classroom.getCapacity() == null) continue;
			if (detail.totalStudents() <= classroom.getCapacity()) continue;
			violations.add(classroomCapacityViolation(item, detail, classroom));
		}
		return violations.size() - before;
	}

	private int detectClassroomTypeViolations(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		Map<Long, Classroom> classroomMap,
		List<AllocationConflictViolation> violations
	) {
		int before = violations.size();
		for (AllocationItem item : items) {
			TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
			Classroom classroom = classroomMap.get(item.getClassroomId());
			if (detail == null || classroom == null) continue;
			String requiredType = normalize(detail.task().getRequiredRoomType());
			String classroomType = normalize(classroom.getClassroomType());
			if (requiredType == null || classroomType == null || requiredType.equals(classroomType)) continue;
			violations.add(classroomTypeViolation(item, detail, classroom, requiredType, classroomType));
		}
		return violations.size() - before;
	}

	private int detectWorkloadViolations(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		List<AllocationConflictViolation> violations
	) {
		log.info("  [workload] start: items={} taskDetails={}" , items.size(), taskDetails.size());
		log.info("  [workload] skipped: max_weekly_hours 字段已移除，暂不检测教师工作量");
		int before = violations.size();

		// max_weekly_hours 字段已移除（2026-06-01 schema 清理）
		// 工作量冲突检测暂时跳过，后续在 teacher_profile 中重新实现
		return violations.size() - before;
	}

	private int detectTeachingTaskHourViolations(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		List<AllocationConflictViolation> violations
	) {
		log.info("  [task-hours] start: items={} taskDetails={}", items.size(), taskDetails.size());
		int before = violations.size();
		Map<Long, List<AllocationItem>> itemsByTaskId = items.stream()
			.filter(item -> item.getTeachingTaskId() != null)
			.collect(Collectors.groupingBy(AllocationItem::getTeachingTaskId, LinkedHashMap::new, Collectors.toList()));
		log.info("  [task-hours] grouped: uniqueTasks={}", itemsByTaskId.size());

		int checked = 0, matched = 0, mismatched = 0;
		for (TeachingTaskDetail detail : taskDetails.values()) {
			TeachingTask task = detail.task();
			if (task.getId() == null || task.getTotalHours() == null) continue;
			List<AllocationItem> taskItems = itemsByTaskId.getOrDefault(task.getId(), List.of());
			int sessionHours = TeachingSessionTimePolicy.periodCount(courseType(detail));
			int actualHours = taskItems.size() * sessionHours;
			int expectedHours = task.getTotalHours();
			checked++;
			if (actualHours == expectedHours) { matched++; continue; }
			mismatched++;

			String courseName = task.getCourse() != null && task.getCourse().getName() != null
				? task.getCourse().getName()
				: "教学任务" + task.getId();
			int diff = expectedHours - actualHours;
			String diffText = diff > 0 ? "缺 " + diff + " 课时" : "多排 " + Math.abs(diff) + " 课时";
			String actionText = diff > 0 ? "增加排课片段" : "减少排课片段";
			String message = "课程《" + courseName + "》计划 " + expectedHours + " 课时，实际排了 "
				+ actualHours + " 课时（" + diffText + "），请返回方案调整页面" + actionText;
			if (taskItems.isEmpty()) {
				violations.add(new AllocationConflictViolation(
					null, TEACHING_TASK_HOURS, message, task.getPrimaryTeacherId(), null, null, null,
					task.getId(), courseName, expectedHours, actualHours
				));
			} else {
				for (AllocationItem item : taskItems) {
					violations.add(new AllocationConflictViolation(
						item.getId(), TEACHING_TASK_HOURS, message, task.getPrimaryTeacherId(), null, item.getClassroomId(), item.getTimeSlotId(),
						task.getId(), courseName, expectedHours, actualHours
					));
				}
			}
		}
		log.info("  [task-hours] done: checked={} matched={} mismatched={} violations={}",
			checked, matched, mismatched, violations.size() - before);
		return violations.size() - before;
	}

	private int detectConflicts(
		List<AllocationItem> items,
		ConflictKeyExtractor keyExtractor,
		ConflictViolationFactory violationFactory,
		List<AllocationConflictViolation> violations
	) {
		int before = violations.size();
		Map<ConflictKey, LinkedHashSet<AllocationItem>> groupedItems = new LinkedHashMap<>();
		for (AllocationItem item : items) {
			for (ConflictKey key : keyExtractor.keys(item)) {
				if (key == null || key.resourceId() == null) continue;
				groupedItems.computeIfAbsent(key, ignored -> new LinkedHashSet<>()).add(item);
			}
		}

		Map<ItemResourceKey, LinkedHashSet<AllocationItem>> conflictsByItem = new LinkedHashMap<>();
		Map<ItemResourceKey, ConflictKey> firstConflictKey = new LinkedHashMap<>();
		for (Map.Entry<ConflictKey, LinkedHashSet<AllocationItem>> entry : groupedItems.entrySet()) {
			if (entry.getValue().size() <= 1) continue;
			for (AllocationItem item : entry.getValue()) {
				ItemResourceKey itemKey = new ItemResourceKey(item, entry.getKey().resourceId());
				conflictsByItem.computeIfAbsent(itemKey, ignored -> new LinkedHashSet<>()).addAll(entry.getValue());
				firstConflictKey.putIfAbsent(itemKey, entry.getKey());
			}
		}
		for (Map.Entry<ItemResourceKey, LinkedHashSet<AllocationItem>> entry : conflictsByItem.entrySet()) {
			ConflictKey conflictKey = firstConflictKey.get(entry.getKey());
			violations.add(violationFactory.create(
				entry.getKey().item(),
				new ArrayList<>(entry.getValue()),
				conflictKey
			));
		}
		return violations.size() - before;
	}

	private List<ConflictKey> teacherKeys(
		AllocationItem item,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots
	) {
		TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
		if (detail == null) return List.of();
		Set<Long> teacherIds = new LinkedHashSet<>();
		if (detail.task().getPrimaryTeacherId() != null) teacherIds.add(detail.task().getPrimaryTeacherId());
		if (detail.task().getAssistantTeacherId() != null) teacherIds.add(detail.task().getAssistantTeacherId());
		List<OccupiedPeriod> occupiedPeriods = occupiedCoordinates(item, taskDetails, timeSlots);
		List<ConflictKey> keys = new ArrayList<>();
		for (Long teacherId : teacherIds) {
			keys.addAll(resourceKeys(teacherId, occupiedPeriods));
		}
		return keys;
	}

	private int detectClassGroupConflicts(
		List<AllocationItem> items,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots,
		List<AllocationConflictViolation> violations
	) {
		Map<Long, String> classGroupNames = taskDetails.values().stream()
			.filter(detail -> detail.task().getClassGroups() != null)
			.flatMap(detail -> detail.task().getClassGroups().stream())
			.filter(classGroup -> classGroup.getId() != null)
			.collect(Collectors.toMap(
				classGroup -> classGroup.getId(),
				classGroup -> classGroup.getName() != null ? classGroup.getName() : "班级" + classGroup.getId(),
				(existing, replacement) -> existing,
				LinkedHashMap::new
			));
		return detectConflicts(
			items,
			item -> classGroupKeys(item, taskDetails, timeSlots),
			(item, group, key) -> classGroupViolation(item, group, key, classGroupNames),
			violations
		);
	}

	private List<ConflictKey> classGroupKeys(
		AllocationItem item,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots
	) {
		TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
		if (detail == null || detail.task().getClassGroups() == null) return List.of();
		List<OccupiedPeriod> occupiedPeriods = occupiedCoordinates(item, taskDetails, timeSlots);
		List<ConflictKey> keys = new ArrayList<>();
		for (var classGroup : detail.task().getClassGroups()) {
			if (classGroup.getId() != null) {
				keys.addAll(resourceKeys(classGroup.getId(), occupiedPeriods));
			}
		}
		return keys;
	}

	private List<ConflictKey> classroomKeys(
		AllocationItem item,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots
	) {
		return resourceKeys(item.getClassroomId(), occupiedCoordinates(item, taskDetails, timeSlots));
	}

	private List<ConflictKey> resourceKeys(Long resourceId, List<OccupiedPeriod> occupiedPeriods) {
		if (resourceId == null || occupiedPeriods.isEmpty()) return List.of();
		return occupiedPeriods.stream()
			.map(occupied -> new ConflictKey(resourceId, occupied))
			.toList();
	}

	private List<OccupiedPeriod> occupiedCoordinates(
		AllocationItem item,
		Map<Long, TeachingTaskDetail> taskDetails,
		TimeSlotCatalog timeSlots
	) {
		TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
		TimeSlot startSlot = timeSlots.byId().get(item.getTimeSlotId());
		if (detail == null || startSlot == null || startSlot.getPeriodIndex() == null) return List.of();
		int periodCount = TeachingSessionTimePolicy.periodCount(courseType(detail));
		List<Integer> periods = TeachingSessionTimePolicy.occupiedPeriods(startSlot.getPeriodIndex(), periodCount);
		if (periods.isEmpty()) return List.of();
		List<OccupiedPeriod> occupied = new ArrayList<>();
		for (int period : periods) {
			TimeCoordinate coordinate = new TimeCoordinate(startSlot.getWeekNumber(), startSlot.getDayOfWeek(), period);
			Long timeSlotId = timeSlots.idByCoordinate().get(coordinate);
			if (timeSlotId == null) return List.of();
			occupied.add(new OccupiedPeriod(coordinate, timeSlotId));
		}
		return occupied;
	}

	private AllocationConflictViolation teacherViolation(
		AllocationItem item,
		List<AllocationItem> group,
		ConflictKey key,
		Map<Long, TeachingTaskDetail> taskDetails
	) {
		TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
		String teacherName = teacherName(detail, key.resourceId());
		return new AllocationConflictViolation(
			item.getId(),
			TEACHER_TIME,
			"教师时间冲突：" + teacherName + " 在" + coordinateLabel(key.occupiedPeriod().coordinate())
				+ " 被重复安排，涉及明细ID：" + itemIds(group),
			key.resourceId(),
			null, null, key.occupiedPeriod().timeSlotId(),
			null, null, null, null
		);
	}

	private AllocationConflictViolation classGroupViolation(
		AllocationItem item,
		List<AllocationItem> group,
		ConflictKey key,
		Map<Long, String> classGroupNames
	) {
		String className = classGroupNames.getOrDefault(key.resourceId(), "班级" + key.resourceId());
		return new AllocationConflictViolation(
			item.getId(),
			CLASS_GROUP_TIME,
			"班级时间冲突：" + className + " 在" + coordinateLabel(key.occupiedPeriod().coordinate())
				+ " 被重复安排，涉及明细ID：" + itemIds(group),
			null, key.resourceId(), null, key.occupiedPeriod().timeSlotId(),
			null, null, null, null
		);
	}

	private AllocationConflictViolation classroomViolation(AllocationItem item, List<AllocationItem> group, ConflictKey key) {
		return new AllocationConflictViolation(
			item.getId(),
			CLASSROOM_TIME,
			"教室时间冲突：教室ID " + item.getClassroomId() + " 在" + coordinateLabel(key.occupiedPeriod().coordinate())
				+ " 被重复占用，涉及明细ID：" + itemIds(group),
			null, null, item.getClassroomId(), key.occupiedPeriod().timeSlotId(),
			null, null, null, null
		);
	}

	private AllocationConflictViolation invalidReferenceViolation(AllocationItem item, String reason) {
		return new AllocationConflictViolation(
			item.getId(),
			INVALID_REFERENCE,
			"无效资源引用：" + reason + "，明细ID " + (item.getId() == null ? "未落库" : item.getId())
				+ "，教学任务ID " + item.getTeachingTaskId() + "，教室ID " + item.getClassroomId()
				+ "，时间段ID " + item.getTimeSlotId(),
			null, null, item.getClassroomId(), item.getTimeSlotId(),
			item.getTeachingTaskId(), null, null, null
		);
	}

	private AllocationConflictViolation invalidTimeBlockViolation(AllocationItem item, String reason) {
		return new AllocationConflictViolation(
			item.getId(),
			INVALID_TIME_BLOCK,
			"非法连排时间块：" + reason + "，明细ID " + (item.getId() == null ? "未落库" : item.getId())
				+ "，教学任务ID " + item.getTeachingTaskId() + "，起始时间段ID " + item.getTimeSlotId(),
			null, null, item.getClassroomId(), item.getTimeSlotId(),
			item.getTeachingTaskId(), null, null, null
		);
	}

	private AllocationConflictViolation duplicateTaskTimeViolation(
		AllocationItem item,
		List<AllocationItem> group,
		ConflictKey key,
		Map<Long, TeachingTaskDetail> taskDetails
	) {
		TeachingTaskDetail detail = taskDetails.get(item.getTeachingTaskId());
		String courseName = courseName(detail, item.getTeachingTaskId());
		return new AllocationConflictViolation(
			item.getId(),
			DUPLICATE_TASK_TIME,
			"教学任务重复时间片：课程《" + courseName + "》在" + coordinateLabel(key.occupiedPeriod().coordinate())
				+ " 出现重叠排课片段，涉及明细ID：" + itemIds(group),
			detail != null ? detail.task().getPrimaryTeacherId() : null,
			null, item.getClassroomId(), key.occupiedPeriod().timeSlotId(),
			item.getTeachingTaskId(), courseName, null, null
		);
	}

	private AllocationConflictViolation classroomCapacityViolation(AllocationItem item, TeachingTaskDetail detail, Classroom classroom) {
		String courseName = courseName(detail, item.getTeachingTaskId());
		return new AllocationConflictViolation(
			item.getId(),
			CLASSROOM_CAPACITY,
			"教室容量不足：课程《" + courseName + "》涉及 " + detail.totalStudents() + " 名学生，教室 "
				+ classroomName(classroom) + " 容量为 " + classroom.getCapacity() + "，时间段ID " + item.getTimeSlotId(),
			detail.task().getPrimaryTeacherId(), null, classroom.getId(), item.getTimeSlotId(),
			item.getTeachingTaskId(), courseName, classroom.getCapacity(), detail.totalStudents()
		);
	}

	private AllocationConflictViolation classroomTypeViolation(
		AllocationItem item,
		TeachingTaskDetail detail,
		Classroom classroom,
		String requiredType,
		String classroomType
	) {
		String courseName = courseName(detail, item.getTeachingTaskId());
		return new AllocationConflictViolation(
			item.getId(),
			CLASSROOM_TYPE,
			"教室类型不匹配：课程《" + courseName + "》要求 " + requiredType + "，实际教室 "
				+ classroomName(classroom) + " 类型为 " + classroomType + "，时间段ID " + item.getTimeSlotId(),
			detail.task().getPrimaryTeacherId(), null, classroom.getId(), item.getTimeSlotId(),
			item.getTeachingTaskId(), courseName, null, null
		);
	}

	private String courseName(TeachingTaskDetail detail, Long taskId) {
		if (detail != null && detail.task().getCourse() != null && detail.task().getCourse().getName() != null) {
			return detail.task().getCourse().getName();
		}
		return "教学任务" + taskId;
	}

	private String courseType(TeachingTaskDetail detail) {
		return detail != null && detail.task().getCourse() != null
			? detail.task().getCourse().getCourseType()
			: null;
	}

	private String teacherName(TeachingTaskDetail detail, Long teacherId) {
		if (detail == null) return "教师" + teacherId;
		Teacher teacher = null;
		if (teacherId != null && teacherId.equals(detail.task().getPrimaryTeacherId())) {
			teacher = detail.task().getPrimaryTeacher();
		} else if (teacherId != null && teacherId.equals(detail.task().getAssistantTeacherId())) {
			teacher = detail.task().getAssistantTeacher();
		}
		return teacher != null && teacher.getName() != null ? teacher.getName() : "教师" + teacherId;
	}

	private String coordinateLabel(TimeCoordinate coordinate) {
		return "第" + coordinate.weekNumber() + "周、星期" + coordinate.dayOfWeek()
			+ "第" + coordinate.periodIndex() + "节";
	}

	private String classroomName(Classroom classroom) {
		return classroom.getName() != null ? classroom.getName() : "教室" + classroom.getId();
	}

	private String normalize(String value) {
		if (value == null || value.isBlank()) {
			return null;
		}
		return value.trim();
	}

	private String itemIds(List<AllocationItem> items) {
		return items.stream()
			.map(item -> item.getId() == null ? "未落库" : item.getId().toString())
			.collect(Collectors.joining(", "));
	}

	private long elapsedMs(long startedAtNanos) {
		return Math.round((System.nanoTime() - startedAtNanos) / 1_000_000.0);
	}

	private void appendSummary(List<String> parts, Map<String, Long> counts, String type, String label) {
		Long count = counts.get(type);
		if (count != null && count > 0) {
			parts.add(label + " " + count + " 条");
		}
	}

	private record TimeCoordinate(Integer weekNumber, Integer dayOfWeek, Integer periodIndex) {
	}

	private record TimeSlotCatalog(Map<Long, TimeSlot> byId, Map<TimeCoordinate, Long> idByCoordinate) {
	}

	private record OccupiedPeriod(TimeCoordinate coordinate, Long timeSlotId) {
	}

	private record ConflictKey(Long resourceId, OccupiedPeriod occupiedPeriod) {
	}

	private record ItemResourceKey(AllocationItem item, Long resourceId) {
	}

	private record TeachingTaskDetail(TeachingTask task, int totalStudents) {
	}

	@FunctionalInterface
	private interface ConflictKeyExtractor {
		List<ConflictKey> keys(AllocationItem item);
	}

	@FunctionalInterface
	private interface ConflictViolationFactory {
		AllocationConflictViolation create(AllocationItem item, List<AllocationItem> group, ConflictKey key);
	}
}
