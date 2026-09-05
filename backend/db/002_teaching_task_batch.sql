-- Add batch/term marker for teaching tasks.
-- Safe when schema.sql already contains the current column/index and safe when
-- an old database was upgraded manually before schema_migration existed.
USE edu_flow_ai;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'teaching_task' AND column_name = 'task_batch'
    ),
    'SELECT 1',
    'ALTER TABLE teaching_task ADD COLUMN task_batch VARCHAR(64) NOT NULL DEFAULT ''DEFAULT'' COMMENT ''教学任务批次/学期/测试用例标识'' AFTER required_room_type'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'teaching_task' AND index_name = 'idx_teaching_task_batch'
    ),
    'SELECT 1',
    'ALTER TABLE teaching_task ADD KEY idx_teaching_task_batch (task_batch)'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;
