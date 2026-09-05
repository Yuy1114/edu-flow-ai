package com.yuy.eduflow.allocation;

/** Explicit registrar acceptance of non-hard publication review items. */
public record AllocationTemplateManualReviewRequest(
	String reason
) {
}
