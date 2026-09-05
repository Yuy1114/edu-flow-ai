package com.yuy.eduflow.allocation;

import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.ml.MlApiProperties;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Thin HTTP adapter for the durable Python scheduling worker.
 *
 * Java deliberately owns no executor or in-memory status. A Java restart can
 * therefore query the same DB-backed Python job instead of reporting IDLE or a
 * stale success for work that was still running.
 */
@Slf4j
@Service
public class V35TemplateGenerationService {

	private static final String RESULT_PREFIX = "EDUFLOW_PIPELINE_RESULT=";
	private static final Pattern RESULT_STATUS = Pattern.compile("\\\"status\\\":\\\"([A-Z_]+)\\\"");
	private static final Set<String> CLIENT_STATUSES = Set.of(
		"IDLE", "RUNNING", "SUCCESS", "NEEDS_MANUAL_REVIEW", "BLOCKED", "FAILED"
	);

	private final RestClient restClient;

	public V35TemplateGenerationService(
		MlApiProperties properties,
		RestClient.Builder restClientBuilder
	) {
		SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
		requestFactory.setConnectTimeout(Duration.ofSeconds(5));
		requestFactory.setReadTimeout(Duration.ofSeconds(30));
		this.restClient = restClientBuilder
			.requestFactory(requestFactory)
			.baseUrl(properties.getUrl())
			.build();
	}

	public V35TemplateGenerationStatus getStatus(Long allocationTaskId) {
		try {
			V35TemplateGenerationStatus status = restClient.get()
				.uri(uriBuilder -> uriBuilder
					.path("/api/ml/pipeline/jobs/latest")
					.queryParam("allocation_task_id", allocationTaskId)
					.build())
				.retrieve()
				.body(V35TemplateGenerationStatus.class);
			return normalize(status);
		} catch (RestClientException exception) {
			log.error("Unable to query formal scheduling job for allocationTaskId={}", allocationTaskId, exception);
			return failed("Python 排课服务不可用：" + conciseMessage(exception));
		}
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
		int requestedTotalWeeks = totalWeeks != null ? totalWeeks : SchedulingTimePolicy.LAST_WEEK;
		if (requestedTotalWeeks < SchedulingTimePolicy.FIRST_WEEK
			|| requestedTotalWeeks > SchedulingTimePolicy.LAST_WEEK) {
			throw new ValidationException("正式排课周数必须在1到18之间");
		}
		Map<String, Object> request = new LinkedHashMap<>();
		request.put("allocationTaskId", allocationTaskId);
		request.put("totalWeeks", requestedTotalWeeks);
		request.put("topK", topK != null ? topK : 300);
		request.put("maxTemplates", maxTemplates != null ? maxTemplates : 8);
		request.put("trainModel", false);
		// This controller endpoint is the formal chain: a successful response must
		// always correspond to queryable DB rows, including when older clients omit
		// the legacy importDb flag.
		request.put("importDb", true);
		request.put("truncateDb", false);

		try {
			V35TemplateGenerationStatus status = restClient.post()
				.uri("/api/ml/pipeline/jobs")
				.contentType(MediaType.APPLICATION_JSON)
				.body(request)
				.retrieve()
				.body(V35TemplateGenerationStatus.class);
			V35TemplateGenerationStatus normalized = normalize(status);
			log.info(
				"Submitted formal scheduling job allocationTaskId={}, jobId={}, status={}",
				allocationTaskId,
				normalized.jobId(),
				normalized.status()
			);
			return normalized;
		} catch (RestClientException exception) {
			log.error("Unable to submit formal scheduling job for allocationTaskId={}", allocationTaskId, exception);
			return failed("Python 排课服务拒绝任务：" + conciseMessage(exception));
		}
	}

	static V35TemplateGenerationStatus normalize(V35TemplateGenerationStatus status) {
		if (status == null || status.status() == null) {
			return failed("排课服务未返回任务状态");
		}
		if ("QUEUED".equals(status.status())) {
			return new V35TemplateGenerationStatus(
				"RUNNING", status.startedAt(), status.progress(), status.error(),
				status.jobId(), status.finishedAt(), status.summaryPath()
			);
		}
		if (!CLIENT_STATUSES.contains(status.status())) {
			return failed("排课服务返回未知状态：" + status.status());
		}
		return status;
	}

	private static V35TemplateGenerationStatus failed(String message) {
		return new V35TemplateGenerationStatus("FAILED", null, 100, message, null, null, null);
	}

	private static String conciseMessage(Exception exception) {
		String message = exception.getMessage();
		if (message == null || message.isBlank()) {
			return exception.getClass().getSimpleName();
		}
		return message.length() <= 500 ? message : message.substring(0, 500) + "...";
	}

	/** Kept as a strict compatibility parser for historical CLI-result tests. */
	static String parsePipelineStatus(String line) {
		if (line == null || !line.startsWith(RESULT_PREFIX)) {
			return null;
		}
		Matcher matcher = RESULT_STATUS.matcher(line.substring(RESULT_PREFIX.length()));
		if (!matcher.find()) {
			throw new IllegalArgumentException("invalid pipeline result line");
		}
		return matcher.group(1);
	}
}
