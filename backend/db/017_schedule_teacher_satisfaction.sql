-- 教师画像满足度的方案级留痕：一次生成 = 多个动态周模板 = 多份候选方案，
-- 每份方案里"谁不满意、哪一维不满意"要在方案详情页直接看到。
--
-- 为什么落库而不是每次打开页面重算：
--   1. 重算需要画像文件（data/profiles/v3/…）和整份 cover，两者都可能已经不在原处；
--   2. 方案的周次分组是生成时的产物，事后用另一份数据重算出来的分数不对应这个方案。
--
-- 为什么两份分数都存：
--   satisfaction_score = 六分量等权平均（与 Java 方案满意度同口径，便于和旧页面比对）；
--   preference_score   = 只对教师已声明的维度取平均，低满足判定按它——
--  否则"只提了一条要求又没被满足"的教师会被未声明维度的 1.0 稀释成 0.83 而看不出问题。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS schedule_teacher_satisfaction (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    allocation_task_id BIGINT NOT NULL,
    generation_run_id VARCHAR(64) NOT NULL,
    template_code VARCHAR(64) NOT NULL COMMENT '动态周模板编码，对应 schedule_template.template_code',
    teacher_key VARCHAR(120) NOT NULL COMMENT '引擎里的教师键：id:<数字> 或 name:<姓名>',
    teacher_id BIGINT NULL COMMENT '画像键是 ID 时才有值；片段只有姓名时为 NULL',
    teacher_name VARCHAR(100) NOT NULL,
    item_count INT NOT NULL DEFAULT 0 COMMENT '该教师在本方案里的排课量（片段×周）',
    days_used INT NOT NULL DEFAULT 0 COMMENT '占用的星期数，紧凑度证据',
    satisfaction_score DOUBLE NOT NULL DEFAULT 0 COMMENT '六分量等权平均 0-1',
    preference_score DOUBLE NOT NULL DEFAULT 0 COMMENT '仅已声明维度的平均 0-1，低满足按它判定',
    low_satisfaction TINYINT(1) NOT NULL DEFAULT 0 COMMENT '生成侧判定的低满足结论，展示端只读不重算',
    declared_dimensions_json TEXT NULL COMMENT '该教师声明过的维度列表',
    components_json TEXT NULL COMMENT '六分量分项满足度',
    evidence_json TEXT NULL COMMENT '命中/超限计数等解释证据',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_teacher_satisfaction (generation_run_id, template_code, teacher_key),
    INDEX idx_teacher_satisfaction_run (allocation_task_id, generation_run_id),
    INDEX idx_teacher_satisfaction_low (generation_run_id, template_code, preference_score),
    CONSTRAINT fk_teacher_satisfaction_task FOREIGN KEY (allocation_task_id) REFERENCES allocation_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
