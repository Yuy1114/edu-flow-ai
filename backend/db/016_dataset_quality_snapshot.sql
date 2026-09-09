-- 训练语料质检快照：每次记录一份清洗产物的统计口径，用于版本对比。
--
-- 历史课表语料本身不进库——它是训练数据，不参与排课决策，25 万行 session 放进
-- MySQL 只会多两张与业务无关的大表，而第二阶段的训练管道是 Python 直读文件的。
-- 但「这批语料长什么样」需要留痕：清洗规则一改，可训练任务数、排除原因分布、
-- 晚间样本量都会变，没有快照就只能凭记忆比较。
--
-- fingerprint 取自**结果内容**而不是文件时间戳：两次清洗只要产出相同就是同一
-- 指纹，所以重复采集不会制造无意义的新行，而口径真变了一定会换指纹。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS dataset_quality_snapshot (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fingerprint VARCHAR(64) NOT NULL COMMENT '清洗结果内容指纹，同口径同指纹',
    dataset_dir VARCHAR(512) NOT NULL COMMENT '产出这份快照的数据集目录',
    source_files INT NOT NULL DEFAULT 0 COMMENT '源班级课表 Excel 份数',
    occurrence_rows INT NOT NULL DEFAULT 0 COMMENT '分班占位行数，含合班重复',
    teaching_sessions INT NOT NULL DEFAULT 0 COMMENT '合并后的物理授课事件数',
    teaching_tasks INT NOT NULL DEFAULT 0 COMMENT '还原出的教学任务数',
    duplicates_removed INT NOT NULL DEFAULT 0 COMMENT '被合并掉的重复记录行数',
    trainable_tasks INT NOT NULL DEFAULT 0 COMMENT '落在可训练范围内的任务数',
    trainable_sessions INT NOT NULL DEFAULT 0 COMMENT '可训练任务的授课次数',
    joint_tasks INT NOT NULL DEFAULT 0 COMMENT '合班任务数',
    evening_sessions INT NOT NULL DEFAULT 0 COMMENT '落在第 9-11 节的授课次数',
    report_json LONGTEXT NULL COMMENT '完整统计口径，含排除原因与按学期分布',
    captured_by VARCHAR(64) NULL COMMENT '触发采集的工号',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_dataset_quality_fingerprint (fingerprint),
    INDEX idx_dataset_quality_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
