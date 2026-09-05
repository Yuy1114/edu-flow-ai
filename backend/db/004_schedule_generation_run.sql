-- Durable state for the formal Java -> Python scheduling worker chain.
-- The generated active key prevents two queued/running jobs for one allocation
-- task while allowing an unlimited terminal history.
USE edu_flow_ai;

CREATE TABLE IF NOT EXISTS schedule_generation_run (
    id VARCHAR(64) PRIMARY KEY,
    allocation_task_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL COMMENT 'QUEUED/RUNNING/SUCCESS/NEEDS_MANUAL_REVIEW/BLOCKED/FAILED',
    pipeline_status VARCHAR(32) NULL COMMENT 'OK/NEEDS_MANUAL_REVIEW/BLOCKED',
    progress INT NOT NULL DEFAULT 0,
    timeout_seconds INT NOT NULL,
    request_json TEXT NOT NULL,
    log_path VARCHAR(500) NULL,
    summary_path VARCHAR(500) NULL,
    error_message TEXT NULL,
    created_at_ms BIGINT NOT NULL,
    started_at_ms BIGINT NULL,
    finished_at_ms BIGINT NULL,
    active_allocation_task_id BIGINT NULL COMMENT '仅在QUEUED/RUNNING时等于allocation_task_id，终态必须置NULL',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_schedule_generation_active_task (active_allocation_task_id),
    KEY idx_schedule_generation_task_created (allocation_task_id, created_at_ms),
    KEY idx_schedule_generation_status (status),
    CONSTRAINT fk_schedule_generation_task
        FOREIGN KEY (allocation_task_id) REFERENCES allocation_task (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
