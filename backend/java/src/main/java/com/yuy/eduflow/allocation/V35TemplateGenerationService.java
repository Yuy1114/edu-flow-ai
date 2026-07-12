package com.yuy.eduflow.allocation;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

@Slf4j
@Service
public class V35TemplateGenerationService {

	private static final Path PROJECT_DIR = Paths.get(System.getProperty("user.dir")).getParent();
	private static final Path PYTHON_VENV = PROJECT_DIR.resolve("python/.venv/bin/python");
	private static final String PYTHON_MODULE = "scheduler.run_pipeline";

	private final ConcurrentHashMap<Long, V35TemplateGenerationStatus> statusMap = new ConcurrentHashMap<>();
	private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
		Thread t = new Thread(r, "v35-pipeline");
		t.setDaemon(true);
		return t;
	});

	public V35TemplateGenerationStatus getStatus(Long allocationTaskId) {
		return statusMap.getOrDefault(allocationTaskId, new V35TemplateGenerationStatus("IDLE", null, 0));
	}

	public V35TemplateGenerationStatus startGeneration(
		Long allocationTaskId,
		Integer totalWeeks,
		Integer topK,
		Integer maxTemplates,
		Boolean trainModel,
		Boolean importDb,
		Boolean truncateDb
	) {
		V35TemplateGenerationStatus existing = statusMap.get(allocationTaskId);
		if (existing != null && "RUNNING".equals(existing.status())) {
			return existing;
		}

		long startedAt = System.currentTimeMillis();
		V35TemplateGenerationStatus running = new V35TemplateGenerationStatus("RUNNING", startedAt, 0);
		statusMap.put(allocationTaskId, running);

		executor.submit(() -> {
			try {
				_runPipeline(allocationTaskId, totalWeeks, topK, maxTemplates, trainModel, importDb, truncateDb);
				statusMap.put(allocationTaskId, new V35TemplateGenerationStatus("SUCCESS", startedAt, 100));
				log.info("V3.5 pipeline completed for allocationTaskId={}", allocationTaskId);
			} catch (Exception e) {
				log.error("V3.5 pipeline failed for allocationTaskId={}", allocationTaskId, e);
				String errorMsg = e.getMessage() != null ? e.getMessage() : "unknown error";
				statusMap.put(allocationTaskId, new V35TemplateGenerationStatus("FAILED", startedAt, 100, errorMsg));
			}
		});

		return running;
	}

	private void _runPipeline(
		Long allocationTaskId,
		Integer totalWeeks,
		Integer topK,
		Integer maxTemplates,
		Boolean trainModel,
		Boolean importDb,
		Boolean truncateDb
	) throws Exception {
		List<String> cmd = new ArrayList<>();
		cmd.add(PYTHON_VENV.toString());
		cmd.add("-m");
		cmd.add(PYTHON_MODULE);
		cmd.add("--allocation-task-id");
		cmd.add(String.valueOf(allocationTaskId));
		cmd.add("--total-weeks");
		cmd.add(String.valueOf(totalWeeks != null ? totalWeeks : 18));
		cmd.add("--top-k");
		cmd.add(String.valueOf(topK != null ? topK : 300));
		cmd.add("--max-templates");
		cmd.add(String.valueOf(maxTemplates != null ? maxTemplates : 8));
		if (Boolean.TRUE.equals(trainModel)) {
			cmd.add("--train-model");
		}
		if (Boolean.TRUE.equals(importDb)) {
			cmd.add("--import-db");
		}
		if (Boolean.TRUE.equals(truncateDb)) {
			cmd.add("--truncate-db");
		}

		ProcessBuilder pb = new ProcessBuilder(cmd);
		pb.directory(PROJECT_DIR.resolve("python").toFile());
		pb.redirectErrorStream(true);
		log.info("Running V3.5 pipeline: {}", String.join(" ", cmd));

		Process process = pb.start();
		StringBuilder output = new StringBuilder();
		try (BufferedReader reader = new BufferedReader(
			new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8)
		)) {
			String line;
			while ((line = reader.readLine()) != null) {
				output.append(line).append("\n");
			}
		}

		int exitCode = process.waitFor();
		if (exitCode != 0) {
			String out = output.toString();
			throw new RuntimeException(
				"V3.5 pipeline exited with code " + exitCode
				+ (out.length() > 500 ? out.substring(0, 500) + "..." : out)
			);
		}
		log.info("V3.5 pipeline output:\n{}", output);
	}
}
