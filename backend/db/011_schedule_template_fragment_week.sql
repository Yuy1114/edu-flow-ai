-- Normalize each template fragment's exact active absolute weeks.
USE edu_flow_ai;

CREATE TABLE IF NOT EXISTS schedule_template_fragment_week (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_fragment_id BIGINT NOT NULL,
    allocation_task_id BIGINT NOT NULL,
    generation_run_id VARCHAR(64) NULL,
    template_id BIGINT NOT NULL,
    week_number INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_template_fragment_week (template_fragment_id, week_number),
    KEY idx_fragment_week_allocation_run (allocation_task_id, generation_run_id, week_number),
    KEY idx_fragment_week_template (template_id, week_number),
    CONSTRAINT fk_fragment_week_fragment FOREIGN KEY (template_fragment_id)
        REFERENCES schedule_template_fragment (id) ON DELETE CASCADE,
    CONSTRAINT fk_fragment_week_template FOREIGN KEY (template_id)
        REFERENCES schedule_template (id) ON DELETE CASCADE,
    CONSTRAINT chk_fragment_week_number CHECK (week_number BETWEEN 1 AND 52)
) COMMENT='模板片段精确生效教学周';

-- Legacy fragments only had duration_weeks. Backfill the earliest N mapped
-- weeks, where N=min(duration_weeks, mapped week count). NULL duration keeps
-- every week mapped to the fragment's template.
INSERT IGNORE INTO schedule_template_fragment_week (
    template_fragment_id,
    allocation_task_id,
    generation_run_id,
    template_id,
    week_number
)
SELECT
    ranked.template_fragment_id,
    ranked.allocation_task_id,
    ranked.generation_run_id,
    ranked.template_id,
    ranked.week_number
FROM (
    SELECT
        fragment.id AS template_fragment_id,
        fragment.allocation_task_id,
        fragment.generation_run_id,
        fragment.template_id,
        mapping.week_number,
        fragment.duration_weeks,
        ROW_NUMBER() OVER (
            PARTITION BY fragment.id ORDER BY mapping.week_number
        ) AS week_rank,
        COUNT(*) OVER (PARTITION BY fragment.id) AS mapped_week_count
    FROM schedule_template_fragment fragment
    JOIN schedule_template_week mapping
      ON mapping.allocation_task_id = fragment.allocation_task_id
     AND mapping.template_id = fragment.template_id
     AND mapping.generation_run_id <=> fragment.generation_run_id
) ranked
WHERE ranked.week_rank <= LEAST(
    COALESCE(NULLIF(ranked.duration_weeks, 0), ranked.mapped_week_count),
    ranked.mapped_week_count
);
