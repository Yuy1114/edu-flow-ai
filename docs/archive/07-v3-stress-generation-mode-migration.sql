-- V3 generation tuning fields for allocation_task_generation_config.
-- Safe for existing demo databases that already contain part of the V3 tuning fields.

SET @schema_name = DATABASE();

SET @sql = IF(
    EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @schema_name
          AND TABLE_NAME = 'allocation_task_generation_config'
          AND COLUMN_NAME = 'placement_top_k'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task_generation_config ADD COLUMN placement_top_k INT NOT NULL DEFAULT 80 COMMENT ''V3 Placement Model TopK candidates per task'' AFTER scheme_count'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = IF(
    EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @schema_name
          AND TABLE_NAME = 'allocation_task_generation_config'
          AND COLUMN_NAME = 'raw_plan_count'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task_generation_config ADD COLUMN raw_plan_count INT NOT NULL DEFAULT 5 COMMENT ''Raw model-guided plan count before CP-SAT filtering'' AFTER placement_top_k'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = IF(
    EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @schema_name
          AND TABLE_NAME = 'allocation_task_generation_config'
          AND COLUMN_NAME = 'cp_plan_count'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task_generation_config ADD COLUMN cp_plan_count INT NOT NULL DEFAULT 3 COMMENT ''Final CP-SAT plan count to keep'' AFTER raw_plan_count'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = IF(
    EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @schema_name
          AND TABLE_NAME = 'allocation_task_generation_config'
          AND COLUMN_NAME = 'solver_time_limit_seconds'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task_generation_config ADD COLUMN solver_time_limit_seconds INT NOT NULL DEFAULT 60 COMMENT ''CP-SAT solver time limit in seconds'' AFTER cp_plan_count'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = IF(
    EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = @schema_name
          AND TABLE_NAME = 'allocation_task_generation_config'
          AND COLUMN_NAME = 'generation_mode'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task_generation_config ADD COLUMN generation_mode VARCHAR(32) NOT NULL DEFAULT ''QUALITY'' COMMENT ''V3 运行模式：FEASIBILITY/QUALITY/STRESS'' AFTER solver_time_limit_seconds'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE allocation_task_generation_config
SET
    placement_top_k = COALESCE(placement_top_k, 80),
    raw_plan_count = COALESCE(raw_plan_count, 5),
    cp_plan_count = COALESCE(cp_plan_count, 3),
    solver_time_limit_seconds = COALESCE(solver_time_limit_seconds, 60),
    generation_mode = COALESCE(NULLIF(generation_mode, ''), 'QUALITY')
WHERE task_id IS NOT NULL;
