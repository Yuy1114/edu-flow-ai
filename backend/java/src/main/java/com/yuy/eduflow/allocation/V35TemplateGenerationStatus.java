package com.yuy.eduflow.allocation;

public record V35TemplateGenerationStatus(
	String status,       // IDLE | RUNNING | SUCCESS | NEEDS_MANUAL_REVIEW | BLOCKED | FAILED
	Long startedAt,
	Integer progress,
	String error,
	String jobId,
	Long finishedAt,
	String summaryPath
) {
	public V35TemplateGenerationStatus(String status, Long startedAt, Integer progress) {
		this(status, startedAt, progress, null, null, null, null);
	}

	public V35TemplateGenerationStatus(String status, Long startedAt, Integer progress, String error) {
		this(status, startedAt, progress, error, null, null, null);
	}
}
