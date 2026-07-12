package com.yuy.eduflow.ml;

import com.yuy.eduflow.common.ApiResponse;

import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/ml/feedback")
public class MlFeedbackTrainingController {
    private final MlFeedbackTrainingService feedbackTrainingService;
    private final MlFeedbackEventService feedbackEventService;
    private final ModelHistoryTrainingService modelHistoryTrainingService;

    public MlFeedbackTrainingController(
        MlFeedbackTrainingService feedbackTrainingService,
        MlFeedbackEventService feedbackEventService,
        ModelHistoryTrainingService modelHistoryTrainingService
    ) {
        this.feedbackTrainingService = feedbackTrainingService;
        this.feedbackEventService = feedbackEventService;
        this.modelHistoryTrainingService = modelHistoryTrainingService;
    }

    @GetMapping("/export")
    public ApiResponse<MlFeedbackExportResult> exportFeedback(@RequestParam(required = false) Long taskId) {
        return ApiResponse.success(feedbackTrainingService.exportFeedback(taskId));
    }

    @GetMapping("/latest-export")
    public ApiResponse<MlFeedbackExportResult> latestFeedbackExport(@RequestParam(required = false) Long taskId) {
        return ApiResponse.success(feedbackTrainingService.latestFeedbackExport(taskId));
    }

    @PostMapping("/train")
    public ApiResponse<MlTrainingStatusResult> train(@RequestParam(required = false) Long taskId) {
        return ApiResponse.success(feedbackTrainingService.train(taskId));
    }

    @PostMapping("/train-from-history")
    public ApiResponse<Map<String, Object>> trainFromHistory(@RequestBody Map<String, String> request) {
        String rawDir = request == null ? null : request.get("rawDir");
        if (rawDir == null || rawDir.isBlank()) {
            throw new com.yuy.eduflow.common.exception.ValidationException("rawDir 不能为空");
        }
        return ApiResponse.success(modelHistoryTrainingService.trainFromHistory(rawDir));
    }

    @GetMapping("/train-from-history/stream")
    public SseEmitter streamTrainFromHistory(@RequestParam String rawDir) {
        if (rawDir == null || rawDir.isBlank()) {
            throw new com.yuy.eduflow.common.exception.ValidationException("rawDir 不能为空");
        }
        return modelHistoryTrainingService.streamTrainFromHistory(rawDir);
    }

    @GetMapping("/training-status")
    public ApiResponse<MlTrainingStatusResult> latestStatus() {
        return ApiResponse.success(feedbackTrainingService.latestStatus());
    }

    @GetMapping("/training-logs")
    public ApiResponse<List<Map<String, Object>>> trainingLogs(@RequestParam(defaultValue = "20") int limit) {
        return ApiResponse.success(feedbackTrainingService.getTrainingLogs(limit));
    }

    @GetMapping("/latest-training")
    public ApiResponse<Map<String, Object>> latestTraining() {
        return ApiResponse.success(feedbackTrainingService.getLatestTrainingLog());
    }

    @GetMapping("/history-dataset/samples")
    public ApiResponse<Map<String, Object>> historyDatasetSamples(
        @RequestParam(defaultValue = "accepted") String quality,
        @RequestParam(defaultValue = "teaching_tasks") String table,
        @RequestParam(required = false) String keyword,
        @RequestParam(required = false) String semester,
        @RequestParam(required = false) String sortBy,
        @RequestParam(defaultValue = "desc") String sortDir,
        @RequestParam(required = false) Integer minHours,
        @RequestParam(required = false) Integer maxHours,
        @RequestParam(defaultValue = "1") int page,
        @RequestParam(defaultValue = "50") int size
    ) {
        return ApiResponse.success(modelHistoryTrainingService.historyDatasetSamples(
            quality,
            table,
            keyword,
            semester,
            sortBy,
            sortDir,
            minHours,
            maxHours,
            page,
            size
        ));
    }

    @GetMapping("/events/summary")
    public ApiResponse<MlFeedbackEventSummary> eventSummary(
        @RequestParam(required = false) Long taskId,
        @RequestParam(defaultValue = "20") int recentLimit
    ) {
        return ApiResponse.success(feedbackEventService.summary(taskId, recentLimit));
    }
}
