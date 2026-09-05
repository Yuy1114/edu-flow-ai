-- V3.5 template-based scheduling tables draft
-- Status: dry-run design, review before applying to production DB.
-- Design doc: docs/architecture/22-V3.5-模板化排课落库设计.md
-- Core idea: template -> week mapping -> template fragments -> occupied slots.

USE edu_flow_ai;

CREATE TABLE IF NOT EXISTS schedule_template (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    allocation_task_id BIGINT NOT NULL COMMENT '排课任务ID',
    generation_run_id VARCHAR(64) NULL COMMENT 'V3.5生成批次ID',
    template_code VARCHAR(64) NOT NULL COMMENT '模板编码，如 cover_v1_template_1',
    template_name VARCHAR(128) NULL COMMENT '模板名称',
    template_order INT NOT NULL DEFAULT 1 COMMENT '模板顺序',
    source_type VARCHAR(32) NOT NULL DEFAULT 'AUTO' COMMENT 'AUTO/MANUAL/ADJUSTED',
    algorithm_version VARCHAR(64) NULL COMMENT '算法版本，如 v3.5-cover-v1',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE/ARCHIVED',
    fragment_count INT NOT NULL DEFAULT 0,
    task_count INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_allocation_run_template_code (allocation_task_id, generation_run_id, template_code),
    KEY idx_allocation_task (allocation_task_id),
    KEY idx_allocation_run (allocation_task_id, generation_run_id)
) COMMENT='排课模板表';

CREATE TABLE IF NOT EXISTS schedule_template_week (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    allocation_task_id BIGINT NOT NULL COMMENT '排课任务ID',
    generation_run_id VARCHAR(64) NULL COMMENT 'V3.5生成批次ID',
    week_number INT NOT NULL COMMENT '教学周',
    template_id BIGINT NOT NULL COMMENT '使用的模板ID',
    template_code VARCHAR(64) NOT NULL COMMENT 'dry-run 阶段用于关联模板编码',
    source_type VARCHAR(32) NOT NULL DEFAULT 'AUTO' COMMENT 'AUTO/MANUAL_ADJUSTED',
    notes VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_allocation_run_week (allocation_task_id, generation_run_id, week_number),
    KEY idx_template (template_id),
    KEY idx_allocation_run (allocation_task_id, generation_run_id),
    KEY idx_allocation_template (allocation_task_id, template_id)
) COMMENT='排课任务每周模板映射表';

CREATE TABLE IF NOT EXISTS schedule_template_fragment (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_id BIGINT NOT NULL COMMENT '模板ID',
    template_code VARCHAR(64) NOT NULL COMMENT 'dry-run 阶段用于关联模板编码',
    allocation_task_id BIGINT NOT NULL COMMENT '排课任务ID',
    generation_run_id VARCHAR(64) NULL COMMENT 'V3.5生成批次ID',
    fragment_code VARCHAR(255) NOT NULL COMMENT '算法片段ID，如 source_key#frag1',
    teaching_task_id BIGINT NULL COMMENT '教学任务ID',
    source_key VARCHAR(255) NULL COMMENT '算法侧任务标识，过渡期使用',
    course_id BIGINT NULL,
    course_name VARCHAR(255) NULL,
    teacher_id BIGINT NULL,
    teacher_name VARCHAR(128) NULL,
    class_group_id BIGINT NULL,
    class_name VARCHAR(128) NULL,
    classroom_id BIGINT NULL,
    classroom_name VARCHAR(128) NOT NULL,
    day_of_week INT NOT NULL COMMENT '星期 1-7',
    period_index INT NOT NULL COMMENT '起始45分钟原子节次，范围1-10',
    consecutive_slots INT NOT NULL DEFAULT 1 COMMENT '连续45分钟节次数，理论=2，上机/实验=4，人工可为1',
    duration_weeks INT NULL COMMENT '课程在当前模板映射周中的有效次数',
    session_hours INT NULL COMMENT '每次课计入的教学课时数',
    required_room_type VARCHAR(32) NULL COMMENT '普通教室/机房',
    source_type VARCHAR(32) NOT NULL DEFAULT 'AUTO' COMMENT 'AUTO/MANUAL/ADJUSTED',
    lock_status VARCHAR(32) NOT NULL DEFAULT 'UNLOCKED' COMMENT 'LOCKED/UNLOCKED',
    score DECIMAL(12, 8) NULL COMMENT 'placement score',
    candidate_rank INT NULL COMMENT '候选排名，fallback 可记为 top_k+1',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_template_fragment_code (template_id, fragment_code),
    KEY idx_template (template_id),
    KEY idx_allocation_task (allocation_task_id),
    KEY idx_allocation_run (allocation_task_id, generation_run_id),
    KEY idx_teaching_task (teaching_task_id),
    KEY idx_template_time (template_id, day_of_week, period_index),
    KEY idx_template_room_time (template_id, classroom_id, day_of_week, period_index),
    KEY idx_template_class_time (template_id, class_group_id, day_of_week, period_index),
    KEY idx_template_teacher_time (template_id, teacher_id, day_of_week, period_index)
) COMMENT='排课模板片段表';

-- A dynamic template may contain fragments active in only part of the weeks
-- mapped to that template. Store the exact absolute weeks instead of inferring
-- them from duration_weeks at query/publication time.
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

CREATE TABLE IF NOT EXISTS schedule_template_fragment_slot (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_fragment_id BIGINT NOT NULL,
    fragment_code VARCHAR(255) NOT NULL COMMENT 'dry-run 阶段用于关联片段编码',
    template_id BIGINT NOT NULL,
    template_code VARCHAR(64) NOT NULL,
    allocation_task_id BIGINT NOT NULL,
    generation_run_id VARCHAR(64) NULL COMMENT 'V3.5生成批次ID',
    teaching_task_id BIGINT NULL,
    classroom_id BIGINT NULL,
    teacher_id BIGINT NULL,
    class_group_id BIGINT NULL,
    day_of_week INT NOT NULL,
    period_index INT NOT NULL COMMENT '实际占用的45分钟原子节次，范围1-10',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_fragment (template_fragment_id),
    KEY idx_allocation_run (allocation_task_id, generation_run_id),
    KEY idx_template_time (template_id, day_of_week, period_index),
    KEY idx_template_room_time (template_id, classroom_id, day_of_week, period_index),
    KEY idx_template_class_time (template_id, class_group_id, day_of_week, period_index),
    KEY idx_template_teacher_time (template_id, teacher_id, day_of_week, period_index)
) COMMENT='模板片段实际课段占用表';

-- 一个教学任务可同时占用主讲教师和助教。不要把多个教师压进 teacher_id 单值列。
CREATE TABLE IF NOT EXISTS schedule_template_fragment_teacher (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_fragment_id BIGINT NOT NULL,
    fragment_code VARCHAR(255) NOT NULL,
    template_id BIGINT NOT NULL,
    template_code VARCHAR(64) NOT NULL,
    allocation_task_id BIGINT NOT NULL,
    generation_run_id VARCHAR(64) NULL,
    teaching_task_id BIGINT NULL,
    teacher_id BIGINT NOT NULL,
    teacher_role VARCHAR(32) NOT NULL COMMENT 'PRIMARY/ASSISTANT',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fragment_teacher (template_fragment_id, teacher_id),
    KEY idx_template_teacher (template_id, teacher_id),
    KEY idx_allocation_run_teacher (allocation_task_id, generation_run_id, teacher_id)
) COMMENT='模板片段-教师多值关联，主讲与助教均参与硬冲突';

-- 一条教学任务通常关联一个或两个班级；关系表保证合班课可按每个班级稳定ID查询。
CREATE TABLE IF NOT EXISTS schedule_template_fragment_class_group (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_fragment_id BIGINT NOT NULL,
    fragment_code VARCHAR(255) NOT NULL,
    template_id BIGINT NOT NULL,
    template_code VARCHAR(64) NOT NULL,
    allocation_task_id BIGINT NOT NULL,
    generation_run_id VARCHAR(64) NULL,
    teaching_task_id BIGINT NULL,
    class_group_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fragment_class_group (template_fragment_id, class_group_id),
    KEY idx_template_class_group (template_id, class_group_id),
    KEY idx_allocation_run_class_group (allocation_task_id, generation_run_id, class_group_id)
) COMMENT='模板片段-班级多值关联，保留合班课的完整稳定ID';

CREATE TABLE IF NOT EXISTS schedule_timetable_entry (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    allocation_task_id BIGINT NOT NULL,
    week_number INT NOT NULL,
    template_id BIGINT NOT NULL,
    template_fragment_id BIGINT NOT NULL,
    teaching_task_id BIGINT NULL,
    course_id BIGINT NULL,
    teacher_id BIGINT NULL,
    class_group_id BIGINT NULL,
    classroom_id BIGINT NULL,
    day_of_week INT NOT NULL,
    period_index INT NOT NULL COMMENT '45分钟原子节次，范围1-10',
    source_type VARCHAR(32) NOT NULL DEFAULT 'TEMPLATE' COMMENT 'TEMPLATE/MANUAL_ADJUSTED',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_week (allocation_task_id, week_number),
    KEY idx_week_class (allocation_task_id, week_number, class_group_id),
    KEY idx_week_teacher (allocation_task_id, week_number, teacher_id),
    KEY idx_week_room (allocation_task_id, week_number, classroom_id)
) COMMENT='最终周课表展开记录表';
