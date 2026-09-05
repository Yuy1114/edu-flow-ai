package com.yuy.eduflow.ml;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuy.eduflow.teachingtask.TeachingTask;
import com.yuy.eduflow.teachingtask.TeachingTaskMapper;
import com.yuy.eduflow.timeslot.TimeSlot;
import com.yuy.eduflow.timeslot.TimeSlotService;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class TeacherProfileFeedbackAggregationService {
    private static final int DEFAULT_EVENT_LIMIT = 2000;

    private final MlFeedbackEventMapper feedbackEventMapper;
    private final TeachingTaskMapper teachingTaskMapper;
    private final TimeSlotService timeSlotService;
    private final ObjectMapper objectMapper;

    public TeacherProfileFeedbackAggregationService(
        MlFeedbackEventMapper feedbackEventMapper,
        TeachingTaskMapper teachingTaskMapper,
        TimeSlotService timeSlotService,
        ObjectMapper objectMapper
    ) {
        this.feedbackEventMapper = feedbackEventMapper;
        this.teachingTaskMapper = teachingTaskMapper;
        this.timeSlotService = timeSlotService;
        this.objectMapper = objectMapper;
    }

    public Map<Long, Map<String, Object>> aggregateByTeacher() {
        Map<Long, Aggregate> aggregates = new LinkedHashMap<>();
        Map<Long, TeachingTask> taskCache = new HashMap<>();
        Map<Long, TimeSlot> slotCache = new HashMap<>();
        for (MlFeedbackEvent event : feedbackEventMapper.findForProfileAggregation(DEFAULT_EVENT_LIMIT)) {
            Long teacherId = resolveTeacherId(event, taskCache);
            if (teacherId == null || teacherId <= 0) {
                continue;
            }
            Aggregate aggregate = aggregates.computeIfAbsent(teacherId, key -> new Aggregate());
            aggregate.addEvent(event.getEventType());
            switch (event.getEventType()) {
                case MlFeedbackEventService.ITEM_MARKED_GOOD -> applyItemSignal(aggregate, event.getAfterSnapshotJson(), slotCache, true, 3);
                case MlFeedbackEventService.ITEM_MARKED_BAD -> applyItemSignal(aggregate, event.getAfterSnapshotJson(), slotCache, false, 3);
                case MlFeedbackEventService.ITEM_MOVED -> {
                    applyItemSignal(aggregate, event.getBeforeSnapshotJson(), slotCache, false, 2);
                    applyItemSignal(aggregate, event.getAfterSnapshotJson(), slotCache, true, 2);
                }
                case MlFeedbackEventService.ADJUSTMENT_APPROVED -> {
                    applyAssignmentSignal(aggregate, event.getBeforeSnapshotJson(), slotCache, false, 4);
                    collectPreferredTimeText(aggregate, event.getContextSnapshotJson());
                }
                case MlFeedbackEventService.ADJUSTMENT_REJECTED -> collectPreferredTimeText(aggregate, event.getContextSnapshotJson());
                default -> {
                }
            }
        }
        Map<Long, Map<String, Object>> result = new LinkedHashMap<>();
        for (Map.Entry<Long, Aggregate> entry : aggregates.entrySet()) {
            result.put(entry.getKey(), entry.getValue().toPayload());
        }
        return result;
    }

    private Long resolveTeacherId(MlFeedbackEvent event, Map<Long, TeachingTask> taskCache) {
        Long teacherId = teacherIdFromContext(event.getContextSnapshotJson());
        if (teacherId != null && teacherId > 0) {
            return teacherId;
        }
        Long teachingTaskId = event.getTeachingTaskId();
        if (teachingTaskId == null || teachingTaskId <= 0) {
            teachingTaskId = teachingTaskIdFromSnapshots(event);
        }
        if (teachingTaskId == null || teachingTaskId <= 0) {
            return null;
        }
        TeachingTask task = taskCache.computeIfAbsent(teachingTaskId, teachingTaskMapper::findById);
        return task == null ? null : task.getPrimaryTeacherId();
    }

    private Long teachingTaskIdFromSnapshots(MlFeedbackEvent event) {
        Map<String, Object> afterItem = map(parseJson(event.getAfterSnapshotJson()).get("item"));
        Long id = longValue(afterItem.get("teaching_task_id"));
        if (id != null && id > 0) {
            return id;
        }
        Map<String, Object> beforeItem = map(parseJson(event.getBeforeSnapshotJson()).get("item"));
        id = longValue(beforeItem.get("teaching_task_id"));
        if (id != null && id > 0) {
            return id;
        }
        Map<String, Object> beforeAssignment = map(parseJson(event.getBeforeSnapshotJson()).get("assignment"));
        return longValue(beforeAssignment.get("teaching_task_id"));
    }

    private Long teacherIdFromContext(String contextJson) {
        Map<String, Object> context = parseJson(contextJson);
        Map<String, Object> source = map(context.get("source"));
        return longValue(source.get("teacher_id"));
    }

    private void applyItemSignal(Aggregate aggregate, String snapshotJson, Map<Long, TimeSlot> slotCache, boolean positive, int weight) {
        Map<String, Object> item = map(parseJson(snapshotJson).get("item"));
        applySlotSignal(aggregate, longValue(item.get("time_slot_id")), slotCache, positive, weight);
    }

    private void applyAssignmentSignal(Aggregate aggregate, String snapshotJson, Map<Long, TimeSlot> slotCache, boolean positive, int weight) {
        Map<String, Object> assignment = map(parseJson(snapshotJson).get("assignment"));
        applySlotSignal(aggregate, longValue(assignment.get("time_slot_id")), slotCache, positive, weight);
    }

    private void applySlotSignal(Aggregate aggregate, Long timeSlotId, Map<Long, TimeSlot> slotCache, boolean positive, int weight) {
        if (timeSlotId == null || timeSlotId <= 0) {
            return;
        }
        TimeSlot slot = slotCache.computeIfAbsent(timeSlotId, id -> {
            try {
                return timeSlotService.findById(id);
            } catch (Exception ignored) {
                return null;
            }
        });
        if (slot == null) {
            return;
        }
        if (positive) {
            aggregate.addPositive(slot.getDayOfWeek(), slot.getPeriodIndex(), weight);
        } else {
            aggregate.addNegative(slot.getDayOfWeek(), slot.getPeriodIndex(), weight);
        }
    }

    private void collectPreferredTimeText(Aggregate aggregate, String contextJson) {
        Map<String, Object> source = map(parseJson(contextJson).get("source"));
        Object value = source.get("preferred_time_text");
        if (value != null && !String.valueOf(value).isBlank()) {
            aggregate.preferredTimeTexts.add(String.valueOf(value));
        }
    }

    private Map<String, Object> parseJson(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<>() {});
        } catch (Exception ignored) {
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

    private Long longValue(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value == null) {
            return null;
        }
        try {
            return Long.parseLong(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static class Aggregate {
        private final Map<String, Integer> eventCounts = new LinkedHashMap<>();
        private final Map<Integer, Integer> positiveWeekdays = new LinkedHashMap<>();
        private final Map<Integer, Integer> negativeWeekdays = new LinkedHashMap<>();
        private final Map<Integer, Integer> positivePeriods = new LinkedHashMap<>();
        private final Map<Integer, Integer> negativePeriods = new LinkedHashMap<>();
        private final List<String> preferredTimeTexts = new ArrayList<>();
        private int positiveWeight;
        private int negativeWeight;

        private void addEvent(String eventType) {
            eventCounts.put(eventType, eventCounts.getOrDefault(eventType, 0) + 1);
        }

        private void addPositive(Integer weekday, Integer period, int weight) {
            positiveWeight += weight;
            add(positiveWeekdays, weekday, weight);
            add(positivePeriods, period, weight);
        }

        private void addNegative(Integer weekday, Integer period, int weight) {
            negativeWeight += weight;
            add(negativeWeekdays, weekday, weight);
            add(negativePeriods, period, weight);
        }

        private void add(Map<Integer, Integer> target, Integer key, int weight) {
            if (key != null && key > 0) {
                target.put(key, target.getOrDefault(key, 0) + weight);
            }
        }

        private Map<String, Object> toPayload() {
            Map<String, Object> profile = new LinkedHashMap<>();
            List<Integer> preferredWeekdays = topKeys(positiveWeekdays, negativeWeekdays, 2, 2);
            List<Integer> preferredPeriods = topKeys(positivePeriods, negativePeriods, 2, 2);
            if (!preferredWeekdays.isEmpty()) {
                profile.put("preferred_weekdays", preferredWeekdays);
            }
            if (!preferredPeriods.isEmpty()) {
                profile.put("preferred_periods", preferredPeriods);
            }
            int earlyNegative = negativePeriods.getOrDefault(1, 0) + negativePeriods.getOrDefault(2, 0);
            int earlyPositive = positivePeriods.getOrDefault(1, 0) + positivePeriods.getOrDefault(2, 0);
            if (earlyNegative >= Math.max(2, earlyPositive + 1)) {
                profile.put("avoid_early_period", true);
            }
            int lateNegative = negativePeriods.getOrDefault(SchedulingTimePolicy.EVENING_FIRST_PERIOD, 0)
                + negativePeriods.getOrDefault(SchedulingTimePolicy.LAST_PERIOD, 0);
            int latePositive = positivePeriods.getOrDefault(SchedulingTimePolicy.EVENING_FIRST_PERIOD, 0)
                + positivePeriods.getOrDefault(SchedulingTimePolicy.LAST_PERIOD, 0);
            if (lateNegative >= Math.max(2, latePositive + 1)) {
                profile.put("avoid_late_period", true);
            }
            if (!preferredTimeTexts.isEmpty()) {
                profile.put("preferred_time_texts", preferredTimeTexts.stream().distinct().limit(5).toList());
            }

            Map<String, Object> evidence = new LinkedHashMap<>();
            evidence.put("event_counts", eventCounts);
            evidence.put("positive_weight", positiveWeight);
            evidence.put("negative_weight", negativeWeight);
            evidence.put("positive_weekdays", positiveWeekdays);
            evidence.put("negative_weekdays", negativeWeekdays);
            evidence.put("positive_periods", positivePeriods);
            evidence.put("negative_periods", negativePeriods);

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("feedback_profile", profile);
            payload.put("feedback_evidence_summary", evidence);
            payload.put("feedback_confidence", confidence());
            return payload;
        }

        private double confidence() {
            double raw = (positiveWeight + negativeWeight) / 8.0;
            return Math.round(Math.min(1.0, raw) * 100.0) / 100.0;
        }

        private List<Integer> topKeys(Map<Integer, Integer> positive, Map<Integer, Integer> negative, int minWeight, int limit) {
            return positive.entrySet().stream()
                .filter(entry -> entry.getValue() >= minWeight)
                .filter(entry -> entry.getValue() > negative.getOrDefault(entry.getKey(), 0))
                .sorted(Map.Entry.<Integer, Integer>comparingByValue(Comparator.reverseOrder()).thenComparing(Map.Entry.comparingByKey()))
                .limit(limit)
                .map(Map.Entry::getKey)
                .toList();
        }
    }
}
