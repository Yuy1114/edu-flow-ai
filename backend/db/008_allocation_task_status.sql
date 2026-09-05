-- Persist the formal scheduling task lifecycle.  Older schemas exposed a
-- status field through Java but never stored it, so confirmations and filters
-- silently lied to callers.
USE edu_flow_ai;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'allocation_task'
          AND column_name = 'status'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task ADD COLUMN status VARCHAR(30) NOT NULL DEFAULT ''CREATED'' COMMENT ''CREATED / RUNNING / GENERATED / NEEDS_MANUAL_REVIEW / BLOCKED / FAILED / CONFIRMED / CANCELLED'' AFTER name'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;

-- Preserve already-confirmed work when upgrading an existing installation.
UPDATE allocation_task task
SET task.status = 'CONFIRMED'
WHERE task.status = 'CREATED'
  AND EXISTS (
      SELECT 1
      FROM allocation_scheme scheme
      WHERE scheme.task_id = task.id
        AND scheme.status = 'CONFIRMED'
  );

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'allocation_task'
          AND index_name = 'idx_allocation_task_status'
    ),
    'SELECT 1',
    'ALTER TABLE allocation_task ADD INDEX idx_allocation_task_status (status)'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;
