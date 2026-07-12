package com.yuy.eduflow.importreview;

import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Comparator;
import java.util.stream.Collectors;
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
public class ImportReviewService {
    private static final Logger log = LoggerFactory.getLogger(ImportReviewService.class);
    private static final long SSE_TIMEOUT_MS = 900_000L;
    private static final String REVIEW_FILE = "import_review_items.csv";
    private static final List<String> HEADERS = List.of(
        "review_id", "review_type", "entity_type", "entity_key", "display_name",
        "field_name", "field_label", "db_id", "db_value", "import_value",
        "status", "decision", "allowed_decisions", "recommended_decision", "reason", "review_note"
    );

    private final Path rootDir;
    private final ExecutorService importExecutor = Executors.newCachedThreadPool();

    public ImportReviewService() {
        this.rootDir = resolveRootDir();
    }

    public List<ImportReviewBatch> findBatches() {
        if (!Files.exists(rootDir)) return List.of();
        try (var stream = Files.list(rootDir)) {
            List<ImportReviewBatch> batches = stream
                .filter(Files::isDirectory)
                .sorted()
                .map(this::toBatch)
                .filter(ImportReviewBatch::isHasReviewFile)
                .toList();
            List<ImportReviewBatch> globalBatches = batches.stream()
                .filter(batch -> batch.getId() != null && batch.getId().startsWith("_global_"))
                .toList();
            return globalBatches.isEmpty() ? batches : globalBatches;
        } catch (IOException e) {
            throw new ValidationException("读取导入审核批次失败");
        }
    }

    public List<ImportReviewItem> findItems(String batchId) {
        Path file = reviewFile(batchId);
        if (!Files.exists(file)) {
            throw new ResourceNotFoundException("导入审核清单不存在");
        }
        return readItems(file, batchId);
    }

    public List<ImportReviewItem> findAllItems() {
        List<ImportReviewItem> allItems = new ArrayList<>();
        for (ImportReviewBatch batch : findBatches()) {
            if (batch.isHasReviewFile()) {
                allItems.addAll(findItems(batch.getId()));
            }
        }
        return allItems;
    }

    public Map<String, Object> saveAllItems(ImportReviewSaveRequest request) {
        if (request == null || request.items() == null) {
            throw new ValidationException("审核项不能为空");
        }
        Map<String, List<ImportReviewItem>> grouped = request.items().stream()
            .filter(item -> item.getBatchId() != null && !item.getBatchId().isBlank())
            .collect(Collectors.groupingBy(ImportReviewItem::getBatchId, LinkedHashMap::new, Collectors.toList()));
        for (Map.Entry<String, List<ImportReviewItem>> entry : grouped.entrySet()) {
            saveItems(entry.getKey(), new ImportReviewSaveRequest(entry.getValue()));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("batchCount", grouped.size());
        result.put("itemCount", request.items().size());
        return result;
    }

    public SseEmitter processFolderStream(String rawDir, String taskBatch, boolean clearExisting) {
        if (rawDir == null || rawDir.isBlank()) {
            throw new ValidationException("原始课表目录不能为空");
        }
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        sendSse(emitter, "log", "准备处理原始课表目录：" + rawDir);

        CompletableFuture.runAsync(() -> {
            try {
                Map<String, Object> result = runBatchProcess(rawDir, taskBatch, clearExisting, line -> sendSse(emitter, "log", line));
                sendSse(emitter, "done", result);
                emitter.complete();
            } catch (Exception e) {
                log.warn("Import review folder processing failed: {}", e.getMessage(), e);
                sendSse(emitter, "failed", Map.of("message", e.getMessage()));
                emitter.completeWithError(e);
            }
        }, importExecutor);

        return emitter;
    }

    public Map<String, Object> saveItems(String batchId, ImportReviewSaveRequest request) {
        if (request == null || request.items() == null) {
            throw new ValidationException("审核项不能为空");
        }
        Path file = reviewFile(batchId);
        if (!Files.exists(file)) {
            throw new ResourceNotFoundException("导入审核清单不存在");
        }
        writeItems(file, request.items());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("batchId", batchId);
        result.put("count", request.items().size());
        result.put("path", file.toString());
        return result;
    }

    public Map<String, Object> apply(String batchId, ImportReviewApplyRequest request) {
        Path dir = reviewFile(batchId).getParent();
        boolean execute = request != null && Boolean.TRUE.equals(request.execute());
        List<ImportReviewItem> items = findItems(batchId);
        long decided = items.stream().filter(item -> item.getDecision() != null && !item.getDecision().isBlank()).count();
        long pending = items.size() - decided;
        if (decided == 0) {
            throw new ValidationException("没有已决策审核项可执行");
        }
        Map<String, Object> result = runApplyScript(dir, execute);
        if (execute) {
            int remaining = pruneDecidedItems(batchId);
            result.put("remainingCount", remaining);
            result.put("processedCount", decided);
        }
        result.put("batchId", batchId);
        result.put("execute", execute);
        result.put("pendingCount", pending);
        return result;
    }

    public Map<String, Object> applyAll(ImportReviewApplyRequest request) {
        boolean execute = request != null && Boolean.TRUE.equals(request.execute());
        List<ImportReviewBatch> batches = findBatches().stream()
            .filter(batch -> batch.getReviewItemCount() > batch.getPendingCount())
            .toList();
        long pending = batches.stream().mapToLong(ImportReviewBatch::getPendingCount).sum();
        if (batches.isEmpty()) {
            throw new ValidationException("没有已决策审核项可执行");
        }
        List<Map<String, Object>> results = new ArrayList<>();
        int successCount = 0;
        for (ImportReviewBatch batch : batches) {
            Map<String, Object> result = apply(batch.getId(), request);
            results.add(result);
            successCount++;
        }
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("status", "ok");
        summary.put("execute", execute);
        summary.put("batchCount", batches.size());
        summary.put("successCount", successCount);
        summary.put("pendingCount", pending);
        summary.put("results", results);
        return summary;
    }

    private int pruneDecidedItems(String batchId) {
        Path file = reviewFile(batchId);
        List<ImportReviewItem> remaining = findItems(batchId).stream()
            .filter(item -> item.getDecision() == null || item.getDecision().isBlank())
            .toList();
        writeItems(file, remaining);
        return remaining.size();
    }

    private void deleteDirectory(Path dir) {
        try (var stream = Files.walk(dir)) {
            List<Path> paths = stream.sorted(Comparator.reverseOrder()).toList();
            for (Path path : paths) {
                Files.deleteIfExists(path);
            }
        } catch (IOException e) {
            throw new ValidationException("删除导入审核批次失败");
        }
    }

    public Map<String, Object> deleteBatch(String batchId) {
        Path dir = reviewFile(batchId).getParent();
        if (!Files.exists(dir)) {
            throw new ResourceNotFoundException("导入审核批次不存在");
        }
        deleteDirectory(dir);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "ok");
        result.put("batchId", batchId);
        result.put("deletedPath", dir.toString());
        return result;
    }

    public Map<String, Object> deleteAllBatches() {
        int count = 0;
        if (Files.exists(rootDir)) {
            try (var stream = Files.list(rootDir)) {
                List<Path> dirs = stream.filter(Files::isDirectory).toList();
                for (Path dir : dirs) {
                    deleteDirectory(dir);
                    count++;
                }
            } catch (IOException e) {
                throw new ValidationException("清空导入审核批次失败");
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "ok");
        result.put("deletedBatchCount", count);
        return result;
    }

    private Map<String, Object> runBatchProcess(String rawDir, String taskBatch, boolean clearExisting, Consumer<String> outputConsumer) {
        Path rawDirPath = resolveRawDir(rawDir);
        Path backendRoot = rootDir.getParent().getParent().getParent();
        Path pythonRoot = backendRoot.resolve("python");
        Path python = resolvePython(pythonRoot);
        if (clearExisting) {
            clearParsedBatches(outputConsumer);
        }

        List<String> command = new ArrayList<>();
        command.add(python.toString());
        command.add("-m");
        command.add("ingest.batch_process_schedule_imports");
        command.add("--input-dir");
        command.add(rawDirPath.toAbsolutePath().toString());
        command.add("--task-batch");
        command.add((taskBatch == null || taskBatch.isBlank()) ? "DEFAULT" : taskBatch);

        log.info("Starting import review folder processing: {}", String.join(" ", command));
        outputConsumer.accept("启动命令：" + String.join(" ", command));
        StringBuilder output = new StringBuilder();
        Process process = null;
        try {
            process = new ProcessBuilder(command)
                .directory(pythonRoot.toFile())
                .redirectErrorStream(true)
                .start();
            Process runningProcess = process;
            CompletableFuture<Void> outputReader = CompletableFuture.runAsync(() -> readProcessOutput(runningProcess, output, outputConsumer), importExecutor);
            boolean finished = process.waitFor(900, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                outputConsumer.accept("导入审核批处理超时，已强制终止");
                throw new ValidationException("导入审核批处理超时");
            }
            outputReader.get(5, TimeUnit.SECONDS);
            if (process.exitValue() != 0) {
                throw new ValidationException("导入审核批处理失败：" + output);
            }
            Map<String, Object> result = parseJsonOutput(output.toString());
            result.put("status", "ok");
            result.put("rawOutput", output.toString());
            result.put("command", String.join(" ", command));
            result.put("batchCount", findBatches().size());
            outputConsumer.accept("导入审核批次生成完成，当前批次数：" + result.get("batchCount"));
            return result;
        } catch (IOException e) {
            outputConsumer.accept("启动导入审核批处理失败：" + e.getMessage());
            throw new ValidationException("启动导入审核批处理失败");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            outputConsumer.accept("导入审核批处理被中断");
            throw new ValidationException("导入审核批处理被中断");
        } catch (Exception e) {
            outputConsumer.accept("导入审核批处理失败：" + e.getMessage());
            if (e instanceof ValidationException validationException) {
                throw validationException;
            }
            throw new ValidationException("导入审核批处理失败");
        } finally {
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }

    private Map<String, Object> runApplyScript(Path importDir, boolean execute) {
        Path backendRoot = rootDir.getParent().getParent().getParent();
        Path pythonRoot = backendRoot.resolve("python");
        Path python = resolvePython(pythonRoot);
        List<String> command = new ArrayList<>();
        command.add(python.toString());
        command.add("-m");
        command.add("ingest.apply_import_review");
        command.add("--input-dir");
        command.add(pythonRoot.relativize(importDir).toString());
        if (execute) {
            command.add("--execute");
        }
        try {
            Process process = new ProcessBuilder(command)
                .directory(pythonRoot.toFile())
                .redirectErrorStream(true)
                .start();
            boolean finished = process.waitFor(120, TimeUnit.SECONDS);
            String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            if (!finished) {
                process.destroyForcibly();
                throw new ValidationException("执行导入脚本超时");
            }
            if (process.exitValue() != 0) {
                throw new ValidationException("执行导入脚本失败：" + output);
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("status", "ok");
            result.put("rawOutput", output);
            result.put("command", String.join(" ", command));
            result.put("reportPath", importDir.resolve("import_apply_report.json").toString());
            return result;
        } catch (IOException e) {
            throw new ValidationException("启动导入脚本失败");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ValidationException("导入脚本执行被中断");
        }
    }

    private ImportReviewBatch toBatch(Path dir) {
        ImportReviewBatch batch = new ImportReviewBatch();
        batch.setId(dir.getFileName().toString());
        batch.setName(dir.getFileName().toString());
        batch.setPath(dir.toString());
        Path file = dir.resolve(REVIEW_FILE);
        batch.setHasReviewFile(Files.exists(file));
        if (Files.exists(file)) {
            List<ImportReviewItem> items = readItems(file, dir.getFileName().toString());
            batch.setReviewItemCount(items.size());
            batch.setPendingCount((int) items.stream().filter(item -> item.getDecision() == null || item.getDecision().isBlank()).count());
            batch.setConflictCount((int) items.stream().filter(item -> "conflict".equals(item.getReviewType())).count());
            batch.setNewItemCount((int) items.stream().filter(item -> "new_item".equals(item.getReviewType())).count());
        }
        return batch;
    }

    private Path reviewFile(String batchId) {
        Path dir = rootDir.resolve(safeBatchId(batchId)).normalize();
        if (!dir.startsWith(rootDir)) {
            throw new ValidationException("非法批次路径");
        }
        return dir.resolve(REVIEW_FILE);
    }

    private String safeBatchId(String batchId) {
        if (batchId == null || batchId.isBlank() || batchId.contains("/") || batchId.contains("\\") || batchId.contains("..")) {
            throw new ValidationException("非法批次 ID");
        }
        return batchId;
    }

    private List<ImportReviewItem> readItems(Path file, String batchId) {
        try {
            List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
            if (!lines.isEmpty() && lines.get(0).startsWith("\uFEFF")) {
                lines.set(0, lines.get(0).substring(1));
            }
            if (lines.isEmpty()) return List.of();
            List<String> headers = parseCsvLine(lines.get(0));
            List<ImportReviewItem> items = new ArrayList<>();
            for (int i = 1; i < lines.size(); i++) {
                if (lines.get(i).isBlank()) continue;
                List<String> values = parseCsvLine(lines.get(i));
                Map<String, String> row = new LinkedHashMap<>();
                for (int index = 0; index < headers.size(); index++) {
                    row.put(headers.get(index), index < values.size() ? values.get(index) : "");
                }
                ImportReviewItem item = toItem(row);
                item.setBatchId(batchId);
                items.add(item);
            }
            return items;
        } catch (IOException e) {
            throw new ValidationException("读取导入审核清单失败");
        }
    }

    private void writeItems(Path file, List<ImportReviewItem> items) {
        List<String> lines = new ArrayList<>();
        lines.add(toCsvLine(HEADERS));
        for (ImportReviewItem item : items) {
            lines.add(toCsvLine(List.of(
                value(item.getReviewId()), value(item.getReviewType()), value(item.getEntityType()), value(item.getEntityKey()),
                value(item.getDisplayName()), value(item.getFieldName()), value(item.getFieldLabel()), value(item.getDbId()),
                value(item.getDbValue()), value(item.getImportValue()), value(item.getStatus()), value(item.getDecision()),
                value(item.getAllowedDecisions()), value(item.getRecommendedDecision()), value(item.getReason()), value(item.getReviewNote())
            )));
        }
        try {
            Files.write(file, lines, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new ValidationException("保存导入审核清单失败");
        }
    }

    private ImportReviewItem toItem(Map<String, String> row) {
        ImportReviewItem item = new ImportReviewItem();
        item.setReviewId(row.getOrDefault("review_id", ""));
        item.setReviewType(row.getOrDefault("review_type", ""));
        item.setEntityType(row.getOrDefault("entity_type", ""));
        item.setEntityKey(row.getOrDefault("entity_key", ""));
        item.setDisplayName(row.getOrDefault("display_name", ""));
        item.setFieldName(row.getOrDefault("field_name", ""));
        item.setFieldLabel(row.getOrDefault("field_label", ""));
        item.setDbId(row.getOrDefault("db_id", ""));
        item.setDbValue(row.getOrDefault("db_value", ""));
        item.setImportValue(row.getOrDefault("import_value", ""));
        item.setStatus(row.getOrDefault("status", ""));
        item.setDecision(row.getOrDefault("decision", ""));
        item.setAllowedDecisions(row.getOrDefault("allowed_decisions", ""));
        item.setRecommendedDecision(row.getOrDefault("recommended_decision", ""));
        item.setReason(row.getOrDefault("reason", ""));
        item.setReviewNote(row.getOrDefault("review_note", ""));
        return item;
    }

    private List<String> parseCsvLine(String line) {
        List<String> result = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (ch == '"') {
                if (quoted && i + 1 < line.length() && line.charAt(i + 1) == '"') {
                    current.append('"');
                    i++;
                } else {
                    quoted = !quoted;
                }
            } else if (ch == ',' && !quoted) {
                result.add(current.toString());
                current.setLength(0);
            } else {
                current.append(ch);
            }
        }
        result.add(current.toString());
        return result;
    }

    private String toCsvLine(List<String> values) {
        return values.stream().map(this::escapeCsv).reduce((a, b) -> a + "," + b).orElse("");
    }

    private String escapeCsv(String value) {
        String text = value(value);
        if (text.contains(",") || text.contains("\"") || text.contains("\n") || text.contains("\r")) {
            return "\"" + text.replace("\"", "\"\"") + "\"";
        }
        return text;
    }

    private String value(String value) {
        return value == null ? "" : value;
    }

    private void readProcessOutput(Process process, StringBuilder output, Consumer<String> outputConsumer) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                synchronized (output) {
                    output.append(line).append(System.lineSeparator());
                }
                log.info("[import-review] {}", line);
                outputConsumer.accept(line);
            }
        } catch (IOException e) {
            log.warn("Failed to read import review output: {}", e.getMessage());
            outputConsumer.accept("读取导入审核日志失败：" + e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseJsonOutput(String output) {
        try {
            int jsonStart = output.indexOf('{');
            if (jsonStart >= 0) {
                return new com.fasterxml.jackson.databind.ObjectMapper().readValue(output.substring(jsonStart), Map.class);
            }
        } catch (Exception e) {
            log.warn("Failed to parse import review output: {}", e.getMessage());
        }
        return new LinkedHashMap<>();
    }

    private void sendSse(SseEmitter emitter, String eventName, Object data) {
        try {
            emitter.send(SseEmitter.event().name(eventName).data(data));
        } catch (IOException e) {
            log.warn("Failed to send import review SSE event: {}", e.getMessage());
        }
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
            if (Files.exists(resolved) && Files.isDirectory(resolved)) {
                return resolved;
            }
        }
        Path asIs = Paths.get(rawDir).normalize();
        if (Files.exists(asIs) && Files.isDirectory(asIs)) {
            return asIs;
        }
        throw new ValidationException("原始课表目录不存在: " + rawDir);
    }

    private Path resolvePython(Path pythonRoot) {
        Path python = pythonRoot.resolve(".venv/bin/python");
        if (Files.exists(python)) {
            return python;
        }
        return Paths.get("python3");
    }

    private void clearParsedBatches(Consumer<String> outputConsumer) {
        if (!Files.exists(rootDir)) {
            return;
        }
        try (var stream = Files.walk(rootDir)) {
            List<Path> paths = stream.sorted(Comparator.reverseOrder()).toList();
            for (Path path : paths) {
                if (!path.equals(rootDir)) {
                    Files.deleteIfExists(path);
                }
            }
            Files.createDirectories(rootDir);
            outputConsumer.accept("已清空旧导入审核批次：" + rootDir);
        } catch (IOException e) {
            throw new ValidationException("清空旧导入审核批次失败");
        }
    }

    private Path resolveRootDir() {
        Path userDir = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        if (userDir.endsWith(Paths.get("backend", "java"))) {
            return userDir.getParent().resolve("data/parsed/schedule_imports").normalize();
        }
        return userDir.resolve("backend/data/parsed/schedule_imports").normalize();
    }
}
