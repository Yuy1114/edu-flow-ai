package com.yuy.eduflow.allocation;

import java.time.LocalDateTime;
import lombok.Data;

@Data
public class AllocationTemplate {
	private Long id;
	private Long allocationTaskId;
	private String generationRunId;
	private String templateCode;
	private String templateName;
	private Integer templateOrder;
	private String sourceType;
	private String algorithmVersion;
	private String status;
	private Integer fragmentCount;
	private Integer taskCount;
	private LocalDateTime createdAt;
	private LocalDateTime updatedAt;
}
