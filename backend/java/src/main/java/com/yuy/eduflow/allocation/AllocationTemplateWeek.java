package com.yuy.eduflow.allocation;

import java.time.LocalDateTime;
import lombok.Data;

@Data
public class AllocationTemplateWeek {
	private Long id;
	private Long allocationTaskId;
	private String generationRunId;
	private Integer weekNumber;
	private Long templateId;
	private String templateCode;
	private String sourceType;
	private String notes;
	private LocalDateTime createdAt;
	private LocalDateTime updatedAt;
}
