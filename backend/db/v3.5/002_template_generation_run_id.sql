-- Upgrade an early V3.5 draft to generation-scoped templates.
-- Every operation is conditional because the current 001 baseline already
-- contains these columns and indexes. This makes 001 -> 002 safe on a new DB
-- and supports old databases that applied either file manually.
USE edu_flow_ai;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template' AND column_name = 'generation_run_id'),
    'SELECT 1',
    'ALTER TABLE schedule_template ADD COLUMN generation_run_id VARCHAR(64) NULL COMMENT ''V3.5生成批次ID'' AFTER allocation_task_id'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template_week' AND column_name = 'generation_run_id'),
    'SELECT 1',
    'ALTER TABLE schedule_template_week ADD COLUMN generation_run_id VARCHAR(64) NULL COMMENT ''V3.5生成批次ID'' AFTER allocation_task_id'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment' AND column_name = 'generation_run_id'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment ADD COLUMN generation_run_id VARCHAR(64) NULL COMMENT ''V3.5生成批次ID'' AFTER allocation_task_id'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment_slot' AND column_name = 'generation_run_id'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment_slot ADD COLUMN generation_run_id VARCHAR(64) NULL COMMENT ''V3.5生成批次ID'' AFTER allocation_task_id'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

-- Atomic-time metadata was added after the first draft. Existing fragment
-- rows remain reviewable when these values are NULL.
SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment' AND column_name = 'duration_weeks'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment ADD COLUMN duration_weeks INT NULL COMMENT ''课程在当前模板映射周中的有效次数'' AFTER consecutive_slots'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment' AND column_name = 'session_hours'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment ADD COLUMN session_hours INT NULL COMMENT ''每次课计入的教学课时数'' AFTER duration_weeks'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template' AND index_name = 'uk_allocation_template_code'),
    'ALTER TABLE schedule_template DROP INDEX uk_allocation_template_code',
    'SELECT 1'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template_week' AND index_name = 'uk_allocation_week'),
    'ALTER TABLE schedule_template_week DROP INDEX uk_allocation_week',
    'SELECT 1'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template' AND index_name = 'uk_allocation_run_template_code'),
    'SELECT 1',
    'ALTER TABLE schedule_template ADD UNIQUE KEY uk_allocation_run_template_code (allocation_task_id, generation_run_id, template_code)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template_week' AND index_name = 'uk_allocation_run_week'),
    'SELECT 1',
    'ALTER TABLE schedule_template_week ADD UNIQUE KEY uk_allocation_run_week (allocation_task_id, generation_run_id, week_number)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template' AND index_name = 'idx_allocation_run'),
    'SELECT 1',
    'ALTER TABLE schedule_template ADD KEY idx_allocation_run (allocation_task_id, generation_run_id)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template_week' AND index_name = 'idx_allocation_run'),
    'SELECT 1',
    'ALTER TABLE schedule_template_week ADD KEY idx_allocation_run (allocation_task_id, generation_run_id)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment' AND index_name = 'idx_allocation_run'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment ADD KEY idx_allocation_run (allocation_task_id, generation_run_id)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'schedule_template_fragment_slot' AND index_name = 'idx_allocation_run'),
    'SELECT 1',
    'ALTER TABLE schedule_template_fragment_slot ADD KEY idx_allocation_run (allocation_task_id, generation_run_id)'
);
PREPARE statement FROM @ddl; EXECUTE statement; DEALLOCATE PREPARE statement;
