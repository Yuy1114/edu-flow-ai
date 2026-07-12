-- 教学任务携带显式课时排布 (已于 2026-07-12 应用到开发库)
-- 关卡规则: 每周次数 × 持续周数 × 每次课时(理论2/上机4) == 总课时, 不自洽拒绝入库.
-- 两字段可选; 缺省时 pattern_builder 按课时查表推算 (pattern_source 区分 explicit/hours_rule/hours_fallback).
ALTER TABLE teaching_task
    ADD COLUMN sessions_per_week INT NULL COMMENT '每周上课次数(课时排布, 可选)',
    ADD COLUMN duration_weeks INT NULL COMMENT '持续周数(课时排布, 可选)';
