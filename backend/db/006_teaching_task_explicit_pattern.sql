-- Optional explicit pattern input for every teaching task. Existing rows stay
-- NULL/NULL so the deterministic total-hours rule remains authoritative until
-- an administrator explicitly records a weekly frequency and duration.
USE edu_flow_ai;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'teaching_task' AND column_name = 'sessions_per_week'
    ),
    'SELECT 1',
    'ALTER TABLE teaching_task ADD COLUMN sessions_per_week INT NULL COMMENT ''每周授课次数；与duration_weeks同时为NULL时由引擎按总课时推导'' AFTER total_hours'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'teaching_task' AND column_name = 'duration_weeks'
    ),
    'SELECT 1',
    'ALTER TABLE teaching_task ADD COLUMN duration_weeks INT NULL COMMENT ''持续教学周数；与sessions_per_week成对设置'' AFTER sessions_per_week'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE()
          AND table_name = 'teaching_task'
          AND constraint_name = 'chk_teaching_task_explicit_pattern'
    ),
    'SELECT 1',
    'ALTER TABLE teaching_task ADD CONSTRAINT chk_teaching_task_explicit_pattern CHECK ((sessions_per_week IS NULL AND duration_weeks IS NULL) OR (sessions_per_week > 0 AND duration_weeks BETWEEN 1 AND 52))'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;
