-- Phase 排课: fragment 增加相对掩码字段 (已于 2026-07-12 应用到开发库)
-- 语义: 课程只在其模板被映射到的前 duration_weeks 个周上生效,
--       换周(交换 schedule_template_week 行)不破坏该语义.
ALTER TABLE schedule_template_fragment
    ADD COLUMN duration_weeks INT NULL COMMENT '课程持续周数(相对掩码: 模板映射周中前N个生效)',
    ADD COLUMN session_hours INT NULL COMMENT '每次课课时数';

-- 合班段的 class_name 是多个班名拼接, 原 128 列宽不够
ALTER TABLE schedule_template_fragment MODIFY class_name VARCHAR(512) NULL;
