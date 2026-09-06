-- 导入批次台账：一次课表导入执行留下一行，记录来源、执行人、时间、状态与摘要统计。
--
-- 之前一次导入的全部痕迹只存在于本地目录里的 CSV 和 JSON 报告，库里看不出
-- 「这批数据是什么时候、谁、从哪个文件导进来的」。教学任务只有一个
-- task_batch 字符串，无法回答来源问题。
--
-- 预览是只读的，不写这张表；只有 --execute 真正落库时才记一行。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS import_batch (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_name VARCHAR(512) NOT NULL COMMENT '导入来源：单个课表文件名或批量目录名',
    source_kind VARCHAR(16) NOT NULL DEFAULT 'DIRECTORY' COMMENT 'FILE 或 DIRECTORY',
    task_batch VARCHAR(64) NOT NULL DEFAULT 'DEFAULT' COMMENT '与 teaching_task.task_batch 对应，用于追溯本批导入的教学任务',
    imported_by VARCHAR(64) NOT NULL DEFAULT 'unknown' COMMENT '执行导入的操作员；第一阶段未接认证时记为本地演示操作员',
    status VARCHAR(16) NOT NULL COMMENT 'APPLIED 已落库 / FAILED 执行失败',
    decision_count INT NOT NULL DEFAULT 0 COMMENT '本次带有人工决定的复核项数',
    created_count INT NOT NULL DEFAULT 0 COMMENT '新增',
    updated_count INT NOT NULL DEFAULT 0 COMMENT '更新（含人工合并）',
    conflict_count INT NOT NULL DEFAULT 0 COMMENT '冲突项总数',
    anomaly_count INT NOT NULL DEFAULT 0 COMMENT '异常：依赖缺失、字段无法自动应用等',
    skipped_count INT NOT NULL DEFAULT 0 COMMENT '显式跳过或保留旧值',
    summary_json TEXT NULL COMMENT '五类计数明细与失败原因的完整摘要',
    error_message VARCHAR(1024) NULL COMMENT 'status=FAILED 时的具体原因',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_import_batch_task_batch (task_batch),
    INDEX idx_import_batch_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
