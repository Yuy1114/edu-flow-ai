package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class V35TemplateGenerationServiceTest {

	@Test
	void parsesTheStructuredPipelineTerminalStatuses() {
		assertEquals(
			"NEEDS_MANUAL_REVIEW",
			V35TemplateGenerationService.parsePipelineStatus(
				"EDUFLOW_PIPELINE_RESULT={\"status\":\"NEEDS_MANUAL_REVIEW\",\"summary\":\"/tmp/run.json\"}"
			)
		);
		assertEquals(
			"BLOCKED",
			V35TemplateGenerationService.parsePipelineStatus(
				"EDUFLOW_PIPELINE_RESULT={\"status\":\"BLOCKED\"}"
			)
		);
	}

	@Test
	void ignoresOrdinaryPipelineLogLinesAndRejectsMalformedResultLines() {
		assertNull(V35TemplateGenerationService.parsePipelineStatus("building patterns"));
		assertThrows(
			IllegalArgumentException.class,
			() -> V35TemplateGenerationService.parsePipelineStatus("EDUFLOW_PIPELINE_RESULT={}")
		);
	}

	@Test
	void mapsDurableWorkerQueueStateToTheExistingFrontendRunningState() {
		V35TemplateGenerationStatus normalized = V35TemplateGenerationService.normalize(
			new V35TemplateGenerationStatus("QUEUED", null, 0, null, "pipeline-1", null, null)
		);

		assertEquals("RUNNING", normalized.status());
		assertEquals("pipeline-1", normalized.jobId());
	}

	@Test
	void failsClosedForUnknownWorkerState() {
		V35TemplateGenerationStatus normalized = V35TemplateGenerationService.normalize(
			new V35TemplateGenerationStatus("MYSTERY", null, 0, null, "pipeline-2", null, null)
		);

		assertEquals("FAILED", normalized.status());
		assertEquals(100, normalized.progress());
	}
}
