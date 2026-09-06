SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS edu_flow_ai
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE edu_flow_ai;

CREATE TABLE IF NOT EXISTS teacher (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    employee_no VARCHAR(50) NOT NULL,
    password VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'TEACHER',
    name VARCHAR(50) NOT NULL,
    department VARCHAR(100) NOT NULL,
    title VARCHAR(50) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_teacher_employee_no (employee_no),
    INDEX idx_teacher_status (status),
    INDEX idx_teacher_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v3: 教师个人倾向（教师自己提交的可用/不可用时间等偏好）
CREATE TABLE IF NOT EXISTS teacher_profile (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    teacher_id BIGINT NOT NULL,
    availability_matrix_json TEXT NULL COMMENT '教师固定周可用性矩阵 JSON，10x7，matrix[period-1][weekday-1]，每节45分钟，-1不可用/0随意/1明确可用',
    profile_note TEXT NULL COMMENT '教师其他排课说明，自然语言，由 LLM 解析为软约束',
    profile_preference_json TEXT NULL COMMENT '教师其他排课说明的 LLM 结构化解析结果 JSON',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_teacher_profile_teacher_id (teacher_id),
    CONSTRAINT fk_teacher_profile_teacher FOREIGN KEY (teacher_id) REFERENCES teacher (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v3: 教师-院系多对多关联（支持一位教师属于多个院系）
CREATE TABLE IF NOT EXISTS teacher_department (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    teacher_id BIGINT NOT NULL,
    department VARCHAR(100) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否为默认院系',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_teacher_dept (teacher_id, department),
    INDEX idx_teacher_dept_department (department),
    INDEX idx_teacher_department_teacher (teacher_id),
    CONSTRAINT fk_teacher_department_teacher FOREIGN KEY (teacher_id) REFERENCES teacher (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS course (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(32) NULL COMMENT '课程代码（如软184、云126）',
    credits DECIMAL(4,1) NULL COMMENT '学分',
    course_type ENUM('理论课','上机课','实验课','实践课') NULL COMMENT '课程分类；上机课/实验课每次默认连续4节',
    required_room_type ENUM('普通教室','机房') NULL COMMENT '所需教室类型：普通教室 / 机房（实践课为NULL）',
    required_hours INT NULL,
    description TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_course_name_code (name, code),
    INDEX idx_course_code (code),
    INDEX idx_course_status (status),
    INDEX idx_course_name (name),
    INDEX idx_course_type (course_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS class_group (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    major VARCHAR(100) NULL,
    department VARCHAR(100) NULL COMMENT '所属院系',
    grade VARCHAR(20) NULL,
    student_count INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_class_group_name (name),
    INDEX idx_class_group_name (name),
    INDEX idx_class_group_major (major)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS classroom (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    building VARCHAR(100) DEFAULT NULL,
    capacity INT NULL COMMENT '教室容量',
    classroom_type ENUM('普通教室','机房') NULL COMMENT '教室物理类型',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_classroom_name (name),
    INDEX idx_classroom_status (status),
    INDEX idx_classroom_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS time_slot (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    week_number INT NOT NULL,
    day_of_week INT NOT NULL,
    period_index INT NOT NULL COMMENT '45分钟原子节次，1-4上午、5-8下午、9-11晚上',
    label VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_time_slot_coordinate (week_number, day_of_week, period_index),
    INDEX idx_time_slot_week_day (week_number, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v2: 教学任务 - 排课最小单元
CREATE TABLE IF NOT EXISTS teaching_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    course_id BIGINT NOT NULL,
    primary_teacher_id BIGINT NOT NULL,
    assistant_teacher_id BIGINT NULL,
    classroom_id BIGINT NULL,
    total_hours INT NOT NULL,
    sessions_per_week INT NULL COMMENT '每周授课次数；与duration_weeks同时为NULL时由引擎按总课时推导',
    duration_weeks INT NULL COMMENT '持续教学周数；与sessions_per_week成对设置',
    required_room_type ENUM('普通教室','机房') NULL COMMENT '教学任务所需教室类型，从 course.required_room_type 继承或覆写',
    task_batch VARCHAR(64) NOT NULL DEFAULT 'DEFAULT' COMMENT '教学任务批次/学期/测试用例标识',
    notes TEXT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_teaching_task_course (course_id),
    INDEX idx_teaching_task_teacher (primary_teacher_id),
    INDEX idx_teaching_task_classroom (classroom_id),
    INDEX idx_teaching_task_status (status),
    INDEX idx_teaching_task_batch (task_batch),
    CONSTRAINT fk_teaching_task_course FOREIGN KEY (course_id) REFERENCES course (id),
    CONSTRAINT fk_teaching_task_teacher FOREIGN KEY (primary_teacher_id) REFERENCES teacher (id),
    CONSTRAINT fk_teaching_task_assistant FOREIGN KEY (assistant_teacher_id) REFERENCES teacher (id),
    CONSTRAINT fk_teaching_task_classroom FOREIGN KEY (classroom_id) REFERENCES classroom (id) ON DELETE SET NULL,
    CONSTRAINT chk_teaching_task_explicit_pattern CHECK (
        (sessions_per_week IS NULL AND duration_weeks IS NULL)
        OR (sessions_per_week > 0 AND duration_weeks BETWEEN 1 AND 52)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v2: 教学任务-班级关联（1-2个班级）
CREATE TABLE IF NOT EXISTS teaching_task_class_group (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    teaching_task_id BIGINT NOT NULL,
    class_group_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ttcg (teaching_task_id, class_group_id),
    INDEX idx_ttcg_task (teaching_task_id),
    INDEX idx_ttcg_group (class_group_id),
    CONSTRAINT fk_ttcg_task FOREIGN KEY (teaching_task_id) REFERENCES teaching_task (id) ON DELETE CASCADE,
    CONSTRAINT fk_ttcg_group FOREIGN KEY (class_group_id) REFERENCES class_group (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v2: 教学任务-候选教室关联（可选，为空时使用院系全部可用教室）
CREATE TABLE IF NOT EXISTS teaching_task_classroom (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    teaching_task_id BIGINT NOT NULL,
    classroom_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ttc (teaching_task_id, classroom_id),
    INDEX idx_ttc_task (teaching_task_id),
    INDEX idx_ttc_classroom (classroom_id),
    CONSTRAINT fk_ttc_task FOREIGN KEY (teaching_task_id) REFERENCES teaching_task (id) ON DELETE CASCADE,
    CONSTRAINT fk_ttc_classroom FOREIGN KEY (classroom_id) REFERENCES classroom (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v9: 排课任务主表只保存任务身份；时间域、方案数和影响因子进入 allocation_task_generation_config
CREATE TABLE IF NOT EXISTS allocation_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'CREATED' COMMENT 'CREATED / RUNNING / GENERATED / NEEDS_MANUAL_REVIEW / BLOCKED / FAILED / CONFIRMED / CANCELLED',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_allocation_task_name (name),
    INDEX idx_allocation_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v10: 排课任务生成配置快照（HARD 时间片裁剪 + V3 Placement/CP-SAT/教师画像 objective 权重）
CREATE TABLE IF NOT EXISTS allocation_task_generation_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id BIGINT NOT NULL,
    allowed_weeks VARCHAR(128) NOT NULL DEFAULT '1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18' COMMENT '允许参与排课的周次，多选结果，逗号分隔',
    allowed_weekdays VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5' COMMENT '允许参与排课的星期，多选结果，1=周一，7=周日',
    allowed_periods VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5,6,7,8' COMMENT '允许自动排课的45分钟原子节次；默认1-8，第9-10节保留给人工调课',
    scheme_count INT NOT NULL DEFAULT 3 COMMENT '生成候选方案数量',
    placement_top_k INT NOT NULL DEFAULT 80 COMMENT 'Placement Model 每个任务保留的候选资源数量',
    raw_plan_count INT NOT NULL DEFAULT 240 COMMENT '每个任务生成的原始 task plan 数量',
    cp_plan_count INT NOT NULL DEFAULT 80 COMMENT '送入 CP-SAT 的每任务 plan 数量上限',
    solver_time_limit_seconds INT NOT NULL DEFAULT 1800 COMMENT 'CP-SAT 每个方案求解时间上限，秒',
    generation_mode VARCHAR(32) NOT NULL DEFAULT 'QUALITY' COMMENT 'V3 运行模式：FEASIBILITY/QUALITY/STRESS',
    teacher_profile_penalty_scale DECIMAL(10,4) NOT NULL DEFAULT 100.0000 COMMENT '教师画像 objective 权重倍率，100=默认，0=关闭，200=翻倍',
    early_period_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.040000 COMMENT '早课惩罚（第1-2节）',
    late_period_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.030000 COMMENT '晚课惩罚（第9-10节）',
    weekend_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.050000 COMMENT '周末排课惩罚',
    model_weight DECIMAL(5,2) NOT NULL DEFAULT 0.60 COMMENT 'L3 LightGBM 权重 (α)',
    llm_weight DECIMAL(5,2) NOT NULL DEFAULT 0.40 COMMENT 'L5 LLM 权重 (β)',
    same_day_weight DECIMAL(7,2) NOT NULL DEFAULT 0.05 COMMENT 'L2 S1: 同日重复安排惩罚',
    capacity_waste_penalty DECIMAL(7,2) NOT NULL DEFAULT 0.00 COMMENT 'L2 S8: 教室容量浪费惩罚',
    teacher_day_load_penalty DECIMAL(7,2) NOT NULL DEFAULT 0.00 COMMENT 'L2 S5: 教师单日过载惩罚',
    class_day_load_penalty DECIMAL(7,2) NOT NULL DEFAULT 0.00 COMMENT 'L2 S6: 班级单日过载惩罚',
    teacher_overload_penalty DECIMAL(7,2) NOT NULL DEFAULT 0.00 COMMENT 'L2 S7: 教师周超量惩罚',
    llm_prompt TEXT NULL COMMENT '教务自然语言策略原文，可选',
    llm_result_json TEXT NULL COMMENT 'LLM Parser 标准化输出快照，可选',
    llm_overrides TEXT NULL COMMENT 'JSON: LLM constraint overrides from constraint editor',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_generation_config_task (task_id),
    CONSTRAINT fk_generation_config_task FOREIGN KEY (task_id) REFERENCES allocation_task (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v2: 排课任务-教学任务关联
CREATE TABLE IF NOT EXISTS allocation_task_teaching_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    allocation_task_id BIGINT NOT NULL,
    teaching_task_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_att (allocation_task_id, teaching_task_id),
    INDEX idx_att_task (allocation_task_id),
    INDEX idx_att_teaching (teaching_task_id),
    CONSTRAINT fk_att_task FOREIGN KEY (allocation_task_id) REFERENCES allocation_task (id) ON DELETE CASCADE,
    CONSTRAINT fk_att_teaching FOREIGN KEY (teaching_task_id) REFERENCES teaching_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v3: 候选方案（Placement Model + CP-SAT 生成，多方案候选 + 评估摘要）
CREATE TABLE IF NOT EXISTS allocation_scheme (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id BIGINT NOT NULL,
    scheme_name VARCHAR(100) NOT NULL,
    summary TEXT NULL,
    scheme_score DOUBLE NULL COMMENT '评估器综合分 0-100',
    evaluation_summary TEXT NULL COMMENT '评估结果 JSON',
    policy VARCHAR(32) NULL COMMENT '生成策略名称',
    policy_params TEXT NULL COMMENT '生成策略参数 JSON',
    model_version VARCHAR(64) NULL COMMENT '模型/排课链路版本，如 v3.5-dynamic-week',
    conflict_summary TEXT NULL,
    valid BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(30) NOT NULL DEFAULT 'CANDIDATE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_allocation_scheme_task (task_id),
    INDEX idx_allocation_scheme_status (status),
    CONSTRAINT fk_allocation_scheme_task FOREIGN KEY (task_id) REFERENCES allocation_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v5: 方案反馈（教务选择/调整/确认行为记录）
CREATE TABLE IF NOT EXISTS allocation_scheme_feedback (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    scheme_id BIGINT NOT NULL,
    task_id BIGINT NOT NULL,
    feedback_type VARCHAR(30) NOT NULL COMMENT 'SELECTED/ADJUSTED/CONFIRMED',
    adjustment_count INT NOT NULL DEFAULT 0 COMMENT '调整次数',
    created_by VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scheme_feedback_scheme (scheme_id),
    INDEX idx_scheme_feedback_task (task_id),
    INDEX idx_scheme_feedback_type (feedback_type),
    CONSTRAINT fk_scheme_feedback_scheme FOREIGN KEY (scheme_id) REFERENCES allocation_scheme (id),
    CONSTRAINT fk_scheme_feedback_task FOREIGN KEY (task_id) REFERENCES allocation_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v5: 人工调整日志（记录每次拖拽/编辑的前后状态）
CREATE TABLE IF NOT EXISTS allocation_item_adjustment_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    scheme_id BIGINT NOT NULL,
    item_id BIGINT NOT NULL,
    teaching_task_id BIGINT NOT NULL,
    from_time_slot_id BIGINT NULL,
    to_time_slot_id BIGINT NULL,
    from_classroom_id BIGINT NULL,
    to_classroom_id BIGINT NULL,
    reason VARCHAR(500) NULL,
    created_by VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_item_adj_scheme (scheme_id),
    INDEX idx_item_adj_item (item_id),
    CONSTRAINT fk_item_adj_scheme FOREIGN KEY (scheme_id) REFERENCES allocation_scheme (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v3: 候选方案排课片段（含 CP-SAT 选择结果与教师画像解释字段）
CREATE TABLE IF NOT EXISTS allocation_item (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    scheme_id BIGINT NOT NULL,
    teaching_task_id BIGINT NOT NULL,
    classroom_id BIGINT NOT NULL,
    time_slot_id BIGINT NOT NULL COMMENT '一次课起始原子时间片；理论/实践占连续2节，上机/实验占连续4节',
    teacher_profile_score DOUBLE NULL COMMENT '教师画像满足度分数 0-1',
    teacher_profile_penalty DOUBLE NULL COMMENT '教师画像软惩罚 0-1',
    teacher_profile_reasons_json TEXT NULL COMMENT '教师画像解释原因 JSON 数组',
    teacher_profile_components_json TEXT NULL COMMENT '教师画像分项满足度 JSON',
    valid BOOLEAN NOT NULL DEFAULT TRUE,
    conflict_message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_allocation_item_scheme (scheme_id),
    INDEX idx_allocation_item_teaching_task (teaching_task_id),
    INDEX idx_allocation_item_classroom_time (classroom_id, time_slot_id),
    CONSTRAINT fk_allocation_item_scheme FOREIGN KEY (scheme_id) REFERENCES allocation_scheme (id),
    CONSTRAINT fk_allocation_item_teaching_task FOREIGN KEY (teaching_task_id) REFERENCES teaching_task (id),
    CONSTRAINT fk_allocation_item_classroom FOREIGN KEY (classroom_id) REFERENCES classroom (id),
    CONSTRAINT fk_allocation_item_time_slot FOREIGN KEY (time_slot_id) REFERENCES time_slot (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v3: 正式课表（候选方案确认后落地）
CREATE TABLE IF NOT EXISTS course_assignment (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_scheme_id BIGINT NULL,
    teaching_task_id BIGINT NOT NULL,
    classroom_id BIGINT NOT NULL,
    time_slot_id BIGINT NOT NULL COMMENT '一次课起始原子时间片；理论/实践占连续2节，上机/实验占连续4节',
    consecutive_slots INT NOT NULL DEFAULT 2 COMMENT '本次授课实际占用的45分钟原子节数；人工补课可为1',
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_course_assignment_scheme (source_scheme_id),
    INDEX idx_course_assignment_teaching_task (teaching_task_id),
    INDEX idx_course_assignment_classroom_time (classroom_id, time_slot_id),
    INDEX idx_course_assignment_status (status),
    CONSTRAINT fk_course_assignment_scheme FOREIGN KEY (source_scheme_id) REFERENCES allocation_scheme (id),
    CONSTRAINT fk_course_assignment_teaching_task FOREIGN KEY (teaching_task_id) REFERENCES teaching_task (id),
    CONSTRAINT fk_course_assignment_classroom FOREIGN KEY (classroom_id) REFERENCES classroom (id),
    CONSTRAINT fk_course_assignment_time_slot FOREIGN KEY (time_slot_id) REFERENCES time_slot (id),
    CONSTRAINT chk_course_assignment_consecutive_slots CHECK (consecutive_slots IN (1, 2, 4))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 全局发布互斥行：确认方案事务先 SELECT ... FOR UPDATE，避免不同排课任务并发发布后相互冲突。
CREATE TABLE IF NOT EXISTS schedule_publication_lock (
    id TINYINT PRIMARY KEY,
    lock_name VARCHAR(64) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_schedule_publication_lock_name (lock_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schedule_publication_lock (id, lock_name)
VALUES (1, 'GLOBAL_SCHEDULE_PUBLICATION')
ON DUPLICATE KEY UPDATE lock_name = VALUES(lock_name);

-- v3: 冲突检测结果（硬冲突、课时不一致等诊断）
CREATE TABLE IF NOT EXISTS conflict_check_result (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    biz_type VARCHAR(30) NOT NULL,
    biz_id BIGINT NOT NULL,
    conflict_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    related_teacher_id BIGINT NULL,
    related_class_group_id BIGINT NULL,
    related_classroom_id BIGINT NULL,
    related_time_slot_id BIGINT NULL,
    teaching_task_id BIGINT NULL,
    course_name VARCHAR(200) NULL,
    expected_hours INT NULL,
    actual_hours INT NULL,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ccr_teaching_task (teaching_task_id),
    INDEX idx_conflict_biz (biz_type, biz_id),
    INDEX idx_conflict_type (conflict_type),
    INDEX idx_conflict_resolved (resolved),
    CONSTRAINT fk_conflict_teacher FOREIGN KEY (related_teacher_id) REFERENCES teacher (id),
    CONSTRAINT fk_conflict_class_group FOREIGN KEY (related_class_group_id) REFERENCES class_group (id),
    CONSTRAINT fk_conflict_classroom FOREIGN KEY (related_classroom_id) REFERENCES classroom (id),
    CONSTRAINT fk_conflict_time_slot FOREIGN KEY (related_time_slot_id) REFERENCES time_slot (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v4: 调课申请
CREATE TABLE IF NOT EXISTS adjustment_request (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    assignment_id BIGINT NOT NULL COMMENT '原正式课表 ID',
    teacher_id BIGINT NOT NULL COMMENT '申请教师 ID',
    reason VARCHAR(500) NOT NULL COMMENT '调课原因',
    preferred_time_text VARCHAR(500) DEFAULT NULL COMMENT '调课倾向（自然语言）',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING / APPROVED / REJECTED',
    review_note VARCHAR(500) DEFAULT NULL COMMENT '审核意见',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_adjustment_teacher (teacher_id),
    INDEX idx_adjustment_status (status),
    CONSTRAINT fk_adjustment_assignment FOREIGN KEY (assignment_id) REFERENCES course_assignment (id),
    CONSTRAINT fk_adjustment_teacher FOREIGN KEY (teacher_id) REFERENCES teacher (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v6: 模型训练日志（记录每次重训的版本、指标、数据来源）
CREATE TABLE IF NOT EXISTS model_training_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    model_version VARCHAR(16) NOT NULL COMMENT '模型版本号，如 v3 / feedback-*',
    training_type VARCHAR(30) NOT NULL COMMENT 'INITIAL / FEEDBACK / FULL',
    scheme_count INT NOT NULL DEFAULT 0 COMMENT '参与训练的方案数',
    item_count INT NOT NULL DEFAULT 0 COMMENT '参与训练的明细数',
    feedback_count INT NOT NULL DEFAULT 0 COMMENT '反馈记录数',
    adjustment_count INT NOT NULL DEFAULT 0 COMMENT '调整记录数',
    conflict_count INT NOT NULL DEFAULT 0 COMMENT '冲突记录数',
    sample_count INT NOT NULL DEFAULT 0 COMMENT '生成样本总数',
    positive_count INT NOT NULL DEFAULT 0 COMMENT '正样本数',
    negative_count INT NOT NULL DEFAULT 0 COMMENT '负样本数',
    train_accuracy DOUBLE NULL COMMENT '训练集准确率',
    train_auc DOUBLE NULL COMMENT '训练集 AUC',
    eval_accuracy DOUBLE NULL COMMENT '验证集准确率',
    eval_auc DOUBLE NULL COMMENT '验证集 AUC',
    model_path VARCHAR(500) NULL COMMENT '模型文件路径',
    sample_path VARCHAR(500) NULL COMMENT '训练样本路径',
    metrics_json TEXT NULL COMMENT '完整指标 JSON',
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING / SUCCEEDED / FAILED',
    error_message TEXT NULL,
    train_started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    train_finished_at DATETIME NULL,
    INDEX idx_training_log_version (model_version),
    INDEX idx_training_log_type (training_type),
    INDEX idx_training_log_status (status),
    INDEX idx_training_log_started (train_started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v7: 反馈事件台账（先沉淀事实，再构建训练样本）
CREATE TABLE IF NOT EXISTS ml_feedback_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_type VARCHAR(50) NOT NULL COMMENT 'SCHEME_CONFIRMED / ITEM_MOVED / ITEM_MARKED_GOOD / ITEM_MARKED_BAD / ADJUSTMENT_APPROVED / ADJUSTMENT_REJECTED',
    task_id BIGINT NOT NULL,
    scheme_id BIGINT NOT NULL,
    item_id BIGINT NULL,
    teaching_task_id BIGINT NULL,
    actor_type VARCHAR(30) NOT NULL DEFAULT 'ADMIN',
    actor_id VARCHAR(100) NULL,
    reason_code VARCHAR(50) NULL,
    reason_text VARCHAR(500) NULL,
    before_snapshot_json TEXT NULL,
    after_snapshot_json TEXT NULL,
    context_snapshot_json TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_feedback_event_task (task_id),
    INDEX idx_feedback_event_scheme (scheme_id),
    INDEX idx_feedback_event_item (item_id),
    INDEX idx_feedback_event_type (event_type),
    INDEX idx_feedback_event_created (created_at),
    CONSTRAINT fk_feedback_event_task FOREIGN KEY (task_id) REFERENCES allocation_task (id),
    CONSTRAINT fk_feedback_event_scheme FOREIGN KEY (scheme_id) REFERENCES allocation_scheme (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
