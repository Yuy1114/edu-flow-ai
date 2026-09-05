package com.yuy.eduflow.ml;

import com.yuy.eduflow.common.exception.BusinessException;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * HTTP client for the Python FastAPI ML service.
 */
@Slf4j
@Component
public class MlApiClient {

	private final RestClient restClient;

	public MlApiClient(MlApiProperties properties, RestClient.Builder restClientBuilder) {
		this.restClient = restClientBuilder
			.requestFactory(new SimpleClientHttpRequestFactory())
			.baseUrl(properties.getUrl())
			.build();
		log.info("MlApiClient initialized: baseUrl={}", properties.getUrl());
	}

	// ── LLM Constraint Translation ───────────────────────────────────

	@SuppressWarnings("unchecked")
	public Map<String, Object> translateConstraint(String text) {
		Map<String, String> body = Map.of("text", text);
		Map<String, Object> response = restClient.post()
			.uri("/api/ml/translate-constraint")
			.contentType(MediaType.APPLICATION_JSON)
			.body(body)
			.retrieve()
			.body(Map.class);
		return response;
	}

	// ── Training ──────────────────────────────────────────────────────

	@SuppressWarnings("unchecked")
	public Map<String, Object> train(Map<String, Object> requestParams) {
		log.info("ML API train starting...");
		Map<String, Object> response = restClient.post()
			.uri("/api/ml/train")
			.contentType(MediaType.APPLICATION_JSON)
			.body(requestParams)
			.retrieve()
			.body(Map.class);
		if (response == null) {
			throw new BusinessException(500, "ML API train returned null");
		}
		Boolean success = (Boolean) response.get("success");
		if (success == null || !success) {
			String error = (String) response.getOrDefault("error", "unknown error");
			throw new BusinessException(500, "ML API train failed: " + error);
		}
		log.info("ML API train done: model={}, samples={}",
			response.get("model_path"), response.get("sample_count"));
		return response;
	}

	// ── Health ────────────────────────────────────────────────────────

	public boolean health() {
		try {
			@SuppressWarnings("unchecked")
			Map<String, Object> result = restClient.get()
				.uri("/api/ml/health")
				.retrieve()
				.body(Map.class);
			return result != null && "ok".equals(result.get("status"));
		} catch (Exception e) {
			log.warn("ML API health check failed: {}", e.getMessage());
			return false;
		}
	}

	@SuppressWarnings("unchecked")
	public Map<String, Object> previewSimulation(Map<String, Object> requestParams) {
		return restClient.post()
			.uri("/api/ml/simulation/preview")
			.contentType(MediaType.APPLICATION_JSON)
			.body(requestParams)
			.retrieve()
			.body(Map.class);
	}

	@SuppressWarnings("unchecked")
	public Map<String, Object> runSimulation(Map<String, Object> requestParams, boolean boundary) {
		return restClient.post()
			.uri(boundary ? "/api/ml/simulation/boundary" : "/api/ml/simulation/run")
			.contentType(MediaType.APPLICATION_JSON)
			.body(requestParams)
			.retrieve()
			.body(Map.class);
	}

	@SuppressWarnings("unchecked")
	public Map<String, Object> querySimulationTimetable(Map<String, Object> requestParams) {
		return restClient.post()
			.uri("/api/ml/simulation/timetable")
			.contentType(MediaType.APPLICATION_JSON)
			.body(requestParams)
			.retrieve()
			.body(Map.class);
	}
}
