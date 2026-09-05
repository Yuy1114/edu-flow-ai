-- Formal V3.5 imports use model_version='v3.5-dynamic-week' (17 chars).
-- Older databases provisioned allocation_scheme.model_version as VARCHAR(16),
-- which fails in MySQL strict mode and used to leave a draft-only half batch.
USE edu_flow_ai;

SET @ddl := IF(
    COALESCE((
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'allocation_scheme'
          AND column_name = 'model_version'
    ), 0) >= 64,
    'SELECT 1',
    'ALTER TABLE allocation_scheme MODIFY COLUMN model_version VARCHAR(64) NULL COMMENT ''模型/排课链路版本，如 v3.5-dynamic-week'''
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;
