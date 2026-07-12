package com.yuy.eduflow.ml;

import com.yuy.eduflow.common.exception.BusinessException;
import com.yuy.eduflow.common.exception.ValidationException;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class ModelHistoryTrainingService {
    private static final Logger log = LoggerFactory.getLogger(ModelHistoryTrainingService.class);
    private static final DateTimeFormatter FILE_TIME_FORMAT = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");
    private static final long SSE_TIMEOUT_MS = 700_000L;
    private static final Set<String> HISTORY_TABLES = Set.of(
        "class_groups",
        "classrooms",
        "courses",
        "teachers",
        "teaching_tasks",
        "timetable_occurrences"
    );

    private final MlFeedbackTrainingMapper mapper;
    private final ExecutorService trainingExecutor = Executors.newCachedThreadPool();

    public ModelHistoryTrainingService(MlFeedbackTrainingMapper mapper) {
        this.mapper = mapper;
    }

    public Map<String, Object> trainFromHistory(String rawDir) {
        return runHistoryTraining(rawDir, line -> {});
    }

    public SseEmitter streamTrainFromHistory(String rawDir) {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        sendSse(emitter, "log", "准备启动历史数据训练：" + rawDir);

        CompletableFuture.runAsync(() -> {
            try {
                Map<String, Object> result = runHistoryTraining(rawDir, line -> sendSse(emitter, "log", line));
                sendSse(emitter, "done", result);
                emitter.complete();
            } catch (Exception e) {
                log.warn("History training stream failed: {}", e.getMessage(), e);
                sendSse(emitter, "failed", Map.of("message", e.getMessage()));
                emitter.completeWithError(e);
            }
        }, trainingExecutor);

        return emitter;
    }

    public Map<String, Object> historyDatasetSamples(
        String quality,
        String table,
        String keyword,
        String semester,
        String sortBy,
        String sortDir,
        Integer minHours,
        Integer maxHours,
        int page,
        int size
    ) {
        String normalizedQuality = normalizeQuality(quality);
        String normalizedTable = normalizeTable(table);
        Path csvPath = resolveHistoryDatasetDir()
            .resolve("review_needed".equals(normalizedQuality) ? "_review_needed" : "_combined")
            .resolve(normalizedTable + ".csv");
        if (!Files.exists(csvPath)) {
            throw new ValidationException("历史训练数据不存在，请先重新生成历史训练集: " + csvPath);
        }

        List<Map<String, String>> rows = readCsv(csvPath);
        List<String> columns = rows.isEmpty() ? List.of() : new ArrayList<>(rows.getFirst().keySet());
        List<Map<String, String>> filtered = filterRows(rows, keyword, semester, minHours, maxHours);
        sortRows(filtered, sortBy, sortDir);

        int safeSize = Math.max(10, Math.min(size, 200));
        int safePage = Math.max(1, page);
        int fromIndex = Math.min((safePage - 1) * safeSize, filtered.size());
        int toIndex = Math.min(fromIndex + safeSize, filtered.size());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("quality", normalizedQuality);
        result.put("table", normalizedTable);
        result.put("path", csvPath.toString());
        result.put("columns", columns);
        result.put("rows", filtered.subList(fromIndex, toIndex));
        result.put("page", safePage);
        result.put("size", safeSize);
        result.put("total", filtered.size());
        result.put("rawTotal", rows.size());
        result.put("summary", summarizeRows(rows, filtered, normalizedTable));
        result.put("sortOptions", sortOptions(normalizedTable, columns));
        result.put("semesters", distinctValues(rows, "source_semester"));
        return result;
    }

    private Map<String, Object> runHistoryTraining(String rawDir, Consumer<String> outputConsumer) {
        Path rawDirPath = resolveRawDir(rawDir);
        List<String> command = new ArrayList<>();
        command.add(resolvePython().toString());
        command.add("-m");
        command.add("ingest.train_from_history");
        command.add("--raw-dir");
        command.add(rawDirPath.toAbsolutePath().toString());
        command.add("--record-db");

        log.info("Starting history training: {}", String.join(" ", command));
        outputConsumer.accept("启动命令：" + String.join(" ", command));

        Path pythonRoot = resolvePythonRoot();
        MlTrainingLog trainingLog = createLog(rawDir);
        mapper.insertTrainingLog(trainingLog);

        Process process = null;
        StringBuilder output = new StringBuilder();
        try {
            process = new ProcessBuilder(command)
                .directory(pythonRoot.toFile())
                .redirectErrorStream(true)
                .start();

            Process runningProcess = process;
            CompletableFuture<Void> outputReader = CompletableFuture.runAsync(() -> readProcessOutput(runningProcess, output, outputConsumer), trainingExecutor);
            boolean finished = process.waitFor(600, TimeUnit.SECONDS);

            if (!finished) {
                process.destroyForcibly();
                updateLog(trainingLog, "FAILED", null, "训练超时");
                outputConsumer.accept("训练超时，已强制终止");
                throw new BusinessException(500, "训练超时");
            }

            outputReader.get(5, TimeUnit.SECONDS);

            if (process.exitValue() != 0) {
                updateLog(trainingLog, "FAILED", null, "训练异常: " + output);
                outputConsumer.accept("训练进程异常退出，exitCode=" + process.exitValue());
                throw new BusinessException(500, "训练异常");
            }

            Map<String, Object> result = parseOutput(output.toString());
            updateLog(trainingLog, "SUCCEEDED", extractSampleCount(result), null);
            log.info("History training done: {} samples", extractSampleCount(result));
            outputConsumer.accept("历史训练完成，样本数：" + (extractSampleCount(result) == null ? "未知" : extractSampleCount(result)));
            return result;
        } catch (IOException e) {
            updateLog(trainingLog, "FAILED", null, "启动训练失败: " + e.getMessage());
            outputConsumer.accept("启动训练失败：" + e.getMessage());
            throw new BusinessException(500, "启动训练失败");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            updateLog(trainingLog, "FAILED", null, "训练被中断");
            outputConsumer.accept("训练被中断");
            throw new BusinessException(500, "训练被中断");
        } catch (Exception e) {
            updateLog(trainingLog, "FAILED", null, "训练失败: " + e.getMessage());
            outputConsumer.accept("训练失败：" + e.getMessage());
            if (e instanceof BusinessException businessException) {
                throw businessException;
            }
            throw new BusinessException(500, "训练失败");
        } finally {
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }

    private void readProcessOutput(Process process, StringBuilder output, Consumer<String> outputConsumer) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                synchronized (output) {
                    output.append(line).append(System.lineSeparator());
                }
                log.info("[history-training] {}", line);
                outputConsumer.accept(line);
            }
        } catch (IOException e) {
            log.warn("Failed to read history training output: {}", e.getMessage());
            outputConsumer.accept("读取训练日志失败：" + e.getMessage());
        }
    }

    private void sendSse(SseEmitter emitter, String eventName, Object data) {
        try {
            emitter.send(SseEmitter.event().name(eventName).data(data));
        } catch (IOException e) {
            log.warn("Failed to send history training SSE event: {}", e.getMessage());
        }
    }

    private MlTrainingLog createLog(String rawDir) {
        MlTrainingLog logEntry = new MlTrainingLog();
        logEntry.setTrainingType("HISTORY");
        logEntry.setModelVersion("v3.5-history");
        logEntry.setStatus("RUNNING");
        logEntry.setErrorMessage("Training from history: " + rawDir);
        logEntry.setTrainStartedAt(LocalDateTime.now());
        return logEntry;
    }

    private void updateLog(MlTrainingLog logEntry, String status, Integer sampleCount, String errorMessage) {
        try {
            logEntry.setStatus(status);
            if (sampleCount != null) {
                logEntry.setSampleCount(sampleCount);
                logEntry.setPositiveCount(sampleCount);
                logEntry.setNegativeCount(0);
            }
            logEntry.setErrorMessage(errorMessage);
            logEntry.setTrainFinishedAt(LocalDateTime.now());
            mapper.updateTrainingLog(logEntry);
        } catch (Exception e) {
            log.warn("Failed to update training log: {}", e.getMessage());
        }
    }

    private Integer extractSampleCount(Map<String, Object> result) {
        if (result == null) return null;
        try {
            var extract = (Map<String, Object>) result.get("extract_result");
            if (extract != null && extract.get("total_samples") instanceof Number n) {
                return n.intValue();
            }
        } catch (Exception ignored) {}
        return null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseOutput(String output) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("rawOutput", output);
        result.put("command", "train_from_history.py");
        try {
            int jsonStart = output.indexOf('{');
            if (jsonStart >= 0) {
                String json = output.substring(jsonStart);
                var parsed = new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
                result.putAll(parsed);
            }
        } catch (Exception e) {
            log.warn("Failed to parse training output: {}", e.getMessage());
        }
        return result;
    }

    private String normalizeQuality(String quality) {
        String value = quality == null ? "" : quality.trim();
        if ("review_needed".equals(value)) return value;
        return "accepted";
    }

    private String normalizeTable(String table) {
        String value = table == null ? "" : table.trim();
        if (!HISTORY_TABLES.contains(value)) {
            throw new ValidationException("不支持的历史训练表: " + table);
        }
        return value;
    }

    private Path resolveHistoryDatasetDir() {
        Path userDir = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        for (int level = 0; level <= 3; level++) {
            Path base = userDir;
            for (int up = 0; up < level; up++) {
                base = base.getParent();
                if (base == null) break;
            }
            if (base == null) continue;
            Path resolved = base.resolve("backend/data/parsed/history_training_dataset").normalize();
            if (Files.exists(resolved) && Files.isDirectory(resolved)) return resolved;
        }
        return userDir.resolve("backend/data/parsed/history_training_dataset").normalize();
    }

    private List<Map<String, String>> readCsv(Path path) {
        try {
            String text = Files.readString(path, StandardCharsets.UTF_8);
            if (!text.isEmpty() && text.charAt(0) == '\uFEFF') {
                text = text.substring(1);
            }
            List<List<String>> records = parseCsvRecords(text);
            if (records.isEmpty()) return List.of();
            List<String> headers = records.getFirst().stream().map(String::trim).toList();
            List<Map<String, String>> rows = new ArrayList<>();
            for (int i = 1; i < records.size(); i++) {
                List<String> record = records.get(i);
                if (record.isEmpty() || record.stream().allMatch(String::isBlank)) continue;
                Map<String, String> row = new LinkedHashMap<>();
                for (int col = 0; col < headers.size(); col++) {
                    String value = col < record.size() ? record.get(col).trim() : "";
                    row.put(headers.get(col), value);
                }
                rows.add(row);
            }
            return rows;
        } catch (IOException e) {
            throw new BusinessException(500, "读取历史训练数据失败");
        }
    }

    private List<List<String>> parseCsvRecords(String text) {
        List<List<String>> records = new ArrayList<>();
        List<String> row = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (quoted) {
                if (ch == '"') {
                    if (i + 1 < text.length() && text.charAt(i + 1) == '"') {
                        field.append('"');
                        i++;
                    } else {
                        quoted = false;
                    }
                } else {
                    field.append(ch);
                }
                continue;
            }
            if (ch == '"') {
                quoted = true;
            } else if (ch == ',') {
                row.add(field.toString());
                field.setLength(0);
            } else if (ch == '\n') {
                row.add(field.toString());
                records.add(row);
                row = new ArrayList<>();
                field.setLength(0);
            } else if (ch != '\r') {
                field.append(ch);
            }
        }
        if (!field.isEmpty() || !row.isEmpty()) {
            row.add(field.toString());
            records.add(row);
        }
        return records;
    }

    private List<Map<String, String>> filterRows(
        List<Map<String, String>> rows,
        String keyword,
        String semester,
        Integer minHours,
        Integer maxHours
    ) {
        String kw = keyword == null ? "" : keyword.trim().toLowerCase();
        String sem = semester == null ? "" : semester.trim();
        return new ArrayList<>(rows.stream()
            .filter(row -> sem.isEmpty() || sem.equals(row.getOrDefault("source_semester", "")))
            .filter(row -> kw.isEmpty() || row.values().stream().anyMatch(value -> value != null && value.toLowerCase().contains(kw)))
            .filter(row -> minHours == null || numericValue(row, "total_hours", "required_hours") >= minHours)
            .filter(row -> maxHours == null || numericValue(row, "total_hours", "required_hours") <= maxHours)
            .toList());
    }

    private void sortRows(List<Map<String, String>> rows, String sortBy, String sortDir) {
        if (sortBy == null || sortBy.isBlank()) return;
        Comparator<Map<String, String>> comparator = Comparator.comparing(row -> row.getOrDefault(sortBy, ""), String.CASE_INSENSITIVE_ORDER);
        if (Set.of("total_hours", "required_hours", "week_index", "day_of_week", "period_index", "student_count", "capacity").contains(sortBy)) {
            comparator = Comparator.comparingInt(row -> numericValue(row, sortBy));
        }
        if ("desc".equalsIgnoreCase(sortDir)) {
            comparator = comparator.reversed();
        }
        rows.sort(comparator);
    }

    private int numericValue(Map<String, String> row, String... keys) {
        for (String key : keys) {
            try {
                String value = row.getOrDefault(key, "").trim();
                if (!value.isEmpty()) return (int) Math.round(Double.parseDouble(value));
            } catch (NumberFormatException ignored) {}
        }
        return 0;
    }

    private Map<String, Object> summarizeRows(List<Map<String, String>> rows, List<Map<String, String>> filtered, String table) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("rawTotal", rows.size());
        summary.put("filteredTotal", filtered.size());
        summary.put("semesterCount", distinctValues(rows, "source_semester").size());
        if ("teaching_tasks".equals(table)) {
            summary.put("hourTotal", filtered.stream().mapToInt(row -> numericValue(row, "total_hours")).sum());
            summary.put("courseCount", distinctValues(filtered, "course_id").size());
            summary.put("teacherCount", distinctTeacherCount(filtered));
            summary.put("classCount", distinctValues(filtered, "class_name").size());
        } else if ("timetable_occurrences".equals(table)) {
            summary.put("courseCount", distinctValues(filtered, "course_id").size());
            summary.put("teacherCount", distinctTeacherCount(filtered));
            summary.put("classroomCount", distinctValues(filtered, "classroom_name").size());
        }
        return summary;
    }

    private List<String> distinctValues(List<Map<String, String>> rows, String key) {
        return rows.stream()
            .map(row -> row.getOrDefault(key, "").trim())
            .filter(value -> !value.isEmpty())
            .distinct()
            .sorted()
            .toList();
    }

    private int distinctTeacherCount(List<Map<String, String>> rows) {
        Set<String> names = new HashSet<>();
        for (Map<String, String> row : rows) {
            for (String name : row.getOrDefault("teacher_name", "").split("[,，、]")) {
                if (!name.isBlank()) names.add(name.trim());
            }
        }
        return names.size();
    }

    private List<String> sortOptions(String table, List<String> columns) {
        List<String> preferred = switch (table) {
            case "teaching_tasks" -> List.of("total_hours", "course_id", "course_code", "course_name", "teacher_name", "class_name", "source_semester");
            case "timetable_occurrences" -> List.of("week_index", "day_of_week", "period_index", "course_id", "course_code", "teacher_name", "classroom_name", "source_semester");
            case "courses" -> List.of("required_hours", "course_id", "course_code", "course_name", "source_semester");
            case "class_groups" -> List.of("student_count", "class_name", "source_semester");
            case "classrooms" -> List.of("classroom_name", "classroom_type", "capacity");
            case "teachers" -> List.of("teacher_name");
            default -> List.of();
        };
        List<String> result = new ArrayList<>();
        for (String option : preferred) {
            if (columns.contains(option)) result.add(option);
        }
        for (String column : columns) {
            if (!result.contains(column)) result.add(column);
        }
        return result;
    }

    private Path resolveRawDir(String rawDir) {
        Path userDir = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        for (int level = 0; level <= 3; level++) {
            Path base = userDir;
            for (int up = 0; up < level; up++) {
                base = base.getParent();
                if (base == null) break;
            }
            if (base == null) continue;
            Path resolved = base.resolve(rawDir).normalize();
            if (resolved.toFile().exists() && resolved.toFile().isDirectory()) {
                return resolved;
            }
        }
        Path asIs = Paths.get(rawDir).normalize();
        if (asIs.toFile().exists() && asIs.toFile().isDirectory()) {
            return asIs;
        }
        throw new ValidationException("原始课表目录不存在: " + rawDir + " (已尝试 5 种路径组合)");
    }

    private Path resolvePython() {
        Path userDir = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        for (int level = 0; level <= 3; level++) {
            Path base = userDir;
            for (int up = 0; up < level; up++) {
                base = base.getParent();
                if (base == null) break;
            }
            if (base == null) continue;
            Path python = base.resolve("python/.venv/bin/python").normalize();
            if (python.toFile().exists()) return python;
        }
        return Paths.get("python3");
    }

    private Path resolvePythonRoot() {
        Path userDir = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        for (int level = 0; level <= 3; level++) {
            Path base = userDir;
            for (int up = 0; up < level; up++) {
                base = base.getParent();
                if (base == null) break;
            }
            if (base == null) continue;
            Path python = base.resolve("python").normalize();
            if (python.toFile().exists() && python.toFile().isDirectory()) return python;
        }
        Path fallback = Paths.get("python");
        if (fallback.toFile().exists()) return fallback;
        return userDir.resolve("python");
    }
}
