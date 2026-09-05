-- 统一时间坐标为每天 10 个 45 分钟原子节次（上午 1-4、下午 5-8、晚上 9-10）。
--
-- 迁移约束：
-- 1. 旧库若只有 period_index 1..5，则视为五个“两节连排”大块，并映射到原子起点 1/3/5/7/9。
-- 2. 映射只修改坐标，不重建旧行，因此 time_slot.id 及其所有外键引用保持不变。
-- 3. 使用 101..105 临时坐标规避 UNIQUE(week_number, day_of_week, period_index) 冲突。
-- 4. 随后补齐第 1-18 周、周一至周日、1-10 节的缺失时间片；脚本可重复执行。
-- 5. 本文件仅供显式迁移执行，不应在应用启动时隐式运行。

USE edu_flow_ai;
SET NAMES utf8mb4;

-- “实验课”是独立课程类型：与上机课一样默认连续4节，但不强制绑定机房。
ALTER TABLE course
    MODIFY course_type ENUM('理论课','上机课','实验课','实践课') NULL
    COMMENT '课程分类；上机课/实验课每次默认连续4节';

-- Persist the discovery result before changing any coordinate.  MySQL DDL
-- auto-commits and migrate.sh only writes its ledger row after this whole file
-- succeeds, so an interrupted migration must not have to infer its original
-- state from already-mutated rows on the next run.
CREATE TABLE IF NOT EXISTS migration_003_time_axis_state (
    id TINYINT PRIMARY KEY,
    legacy_five_block BOOLEAN NOT NULL,
    coordinates_mapped BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_periods_expanded BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @time_slot_count := (SELECT COUNT(*) FROM time_slot);
SET @legacy_temp_count := (
    SELECT COUNT(*) FROM time_slot WHERE period_index BETWEEN 101 AND 105
);
SET @legacy_direct_count := (
    SELECT COUNT(*) FROM time_slot WHERE period_index BETWEEN 1 AND 5
);
SET @non_legacy_direct_count := (
    SELECT COUNT(*) FROM time_slot
    WHERE period_index NOT BETWEEN 1 AND 5
      AND period_index NOT BETWEEN 101 AND 105
);
SET @legacy_odd_only_count := (
    SELECT COUNT(*) FROM time_slot
    WHERE period_index NOT IN (1, 3, 5, 7, 9)
      AND period_index NOT BETWEEN 101 AND 105
);

INSERT IGNORE INTO migration_003_time_axis_state (
    id,
    legacy_five_block,
    coordinates_mapped,
    allowed_periods_expanded
)
VALUES (
    1,
    IF(
        @legacy_temp_count > 0
        OR (@time_slot_count > 0 AND @legacy_direct_count > 0 AND @non_legacy_direct_count = 0)
        -- Resume a pre-fix run that was interrupted after 1..5 became
        -- 1/3/5/7/9 but before allowed_periods was expanded.
        OR (@time_slot_count > 0 AND @legacy_odd_only_count = 0),
        TRUE,
        FALSE
    ),
    IF(
        @legacy_temp_count = 0
        AND @time_slot_count > 0
        AND @legacy_odd_only_count = 0
        AND @non_legacy_direct_count > 0,
        TRUE,
        FALSE
    ),
    FALSE
);

SET @legacy_five_block := (
    SELECT legacy_five_block FROM migration_003_time_axis_state WHERE id = 1
);
SET @coordinates_mapped := (
    SELECT coordinates_mapped FROM migration_003_time_axis_state WHERE id = 1
);

START TRANSACTION;
UPDATE time_slot
SET period_index = period_index + 100
WHERE @legacy_five_block = 1
  AND @coordinates_mapped = 0
  AND period_index BETWEEN 1 AND 5;

UPDATE time_slot
SET period_index = CASE period_index
    WHEN 101 THEN 1
    WHEN 102 THEN 3
    WHEN 103 THEN 5
    WHEN 104 THEN 7
    WHEN 105 THEN 9
    ELSE period_index
END
WHERE @legacy_five_block = 1
  AND @coordinates_mapped = 0
  AND period_index BETWEEN 101 AND 105;

UPDATE migration_003_time_axis_state
SET coordinates_mapped = TRUE
WHERE id = 1
  AND @legacy_five_block = 1
  AND @coordinates_mapped = 0;
COMMIT;

-- 旧配置选择的是五个两节大块；每个已选大块展开为对应的两个原子节次。
-- Coordinate conversion and this marker update share a transaction.  The
-- expansion and its marker also share one transaction, so even allowed-period
-- sets such as "1,2" (whose first expansion still matches ^[1-5]) cannot be
-- expanded twice after a process kill.
SET @allowed_periods_expanded := (
    SELECT allowed_periods_expanded FROM migration_003_time_axis_state WHERE id = 1
);
START TRANSACTION;
UPDATE allocation_task_generation_config
SET allowed_periods = CONCAT_WS(',',
    IF(FIND_IN_SET('1', REPLACE(allowed_periods, ' ', '')) > 0, '1,2', NULL),
    IF(FIND_IN_SET('2', REPLACE(allowed_periods, ' ', '')) > 0, '3,4', NULL),
    IF(FIND_IN_SET('3', REPLACE(allowed_periods, ' ', '')) > 0, '5,6', NULL),
    IF(FIND_IN_SET('4', REPLACE(allowed_periods, ' ', '')) > 0, '7,8', NULL),
    IF(FIND_IN_SET('5', REPLACE(allowed_periods, ' ', '')) > 0, '9,10', NULL)
)
WHERE @legacy_five_block = 1
  AND @allowed_periods_expanded = 0
  AND REPLACE(allowed_periods, ' ', '') REGEXP '^[1-5](,[1-5])*$';

UPDATE migration_003_time_axis_state
SET allowed_periods_expanded = TRUE
WHERE id = 1
  AND @legacy_five_block = 1
  AND @allowed_periods_expanded = 0;
COMMIT;

INSERT IGNORE INTO time_slot (week_number, day_of_week, period_index, label)
SELECT weeks.week_number,
       weekdays.day_of_week,
       periods.period_index,
       CONCAT('第', weeks.week_number, '周 周', weekdays.day_of_week, ' 第', periods.period_index, '节')
FROM (
    SELECT 1 AS week_number UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
    UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
    UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL SELECT 16
    UNION ALL SELECT 17 UNION ALL SELECT 18
) weeks
CROSS JOIN (
    SELECT 1 AS day_of_week UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7
) weekdays
CROSS JOIN (
    SELECT 1 AS period_index UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
    UNION ALL SELECT 9 UNION ALL SELECT 10
) periods;

UPDATE time_slot
SET label = CONCAT('第', week_number, '周 周', day_of_week, ' 第', period_index, '节')
WHERE period_index BETWEEN 1 AND 10;

-- 老的 5x7 教师矩阵按每个旧大块拆成相同的两个 45 分钟节次，保留原语义。
UPDATE teacher_profile
SET availability_matrix_json = JSON_ARRAY(
    JSON_EXTRACT(availability_matrix_json, '$[0]'),
    JSON_EXTRACT(availability_matrix_json, '$[0]'),
    JSON_EXTRACT(availability_matrix_json, '$[1]'),
    JSON_EXTRACT(availability_matrix_json, '$[1]'),
    JSON_EXTRACT(availability_matrix_json, '$[2]'),
    JSON_EXTRACT(availability_matrix_json, '$[2]'),
    JSON_EXTRACT(availability_matrix_json, '$[3]'),
    JSON_EXTRACT(availability_matrix_json, '$[3]'),
    JSON_EXTRACT(availability_matrix_json, '$[4]'),
    JSON_EXTRACT(availability_matrix_json, '$[4]')
)
WHERE availability_matrix_json IS NOT NULL
  AND JSON_VALID(availability_matrix_json)
  AND JSON_TYPE(JSON_EXTRACT(availability_matrix_json, '$')) = 'ARRAY'
  AND JSON_LENGTH(availability_matrix_json) = 5;

ALTER TABLE teacher_profile
    MODIFY availability_matrix_json TEXT NULL
    COMMENT '教师固定周可用性矩阵 JSON，10x7，matrix[period-1][weekday-1]，每节45分钟，-1不可用/0随意/1明确可用';

ALTER TABLE allocation_task_generation_config
    MODIFY allowed_periods VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5,6,7,8'
    COMMENT '允许自动排课的45分钟原子节次；默认1-8，第9-10节保留给人工调课',
    MODIFY early_period_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.040000
    COMMENT '早课惩罚（第1-2节）',
    MODIFY late_period_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.030000
    COMMENT '晚课惩罚（第9-10节）';

-- 执行后应得到 18 * 7 * 10 = 1260 个标准坐标；如果保留了18周以外的历史行，总数可以更大。
SELECT COUNT(*) AS canonical_time_slot_count
FROM time_slot
WHERE week_number BETWEEN 1 AND 18
  AND day_of_week BETWEEN 1 AND 7
  AND period_index BETWEEN 1 AND 10;

SELECT COUNT(*) AS invalid_period_count
FROM time_slot
WHERE period_index NOT BETWEEN 1 AND 10;

-- 旧数据不做有歧义的自动合并。若上机/实验课过去按两个“两节大块”保存，
-- 这里会显式报出非法起点，需重新生成候选或由人工确认一次课的真实起点。
SELECT 'allocation_item' AS source_table, COUNT(*) AS invalid_session_block_count
FROM allocation_item ai
JOIN teaching_task tt ON tt.id = ai.teaching_task_id
JOIN course c ON c.id = tt.course_id
JOIN time_slot ts ON ts.id = ai.time_slot_id
WHERE (c.course_type IN ('理论课', '实践课') AND ts.period_index NOT IN (1, 3, 5, 7, 9))
   OR (c.course_type IN ('上机课', '实验课') AND ts.period_index NOT IN (1, 5))
UNION ALL
SELECT 'course_assignment' AS source_table, COUNT(*) AS invalid_session_block_count
FROM course_assignment ca
JOIN teaching_task tt ON tt.id = ca.teaching_task_id
JOIN course c ON c.id = tt.course_id
JOIN time_slot ts ON ts.id = ca.time_slot_id
WHERE (c.course_type IN ('理论课', '实践课') AND ts.period_index NOT IN (1, 3, 5, 7, 9))
   OR (c.course_type IN ('上机课', '实验课') AND ts.period_index NOT IN (1, 5));

DROP PROCEDURE IF EXISTS assert_atomic_time_axis_migration;
DELIMITER //
CREATE PROCEDURE assert_atomic_time_axis_migration()
BEGIN
    DECLARE invalid_coordinate_count BIGINT DEFAULT 0;
    DECLARE invalid_session_block_count BIGINT DEFAULT 0;

    SELECT COUNT(*) INTO invalid_coordinate_count
    FROM time_slot
    WHERE period_index NOT BETWEEN 1 AND 10;

    SELECT
        (SELECT COUNT(*)
         FROM allocation_item ai
         JOIN teaching_task tt ON tt.id = ai.teaching_task_id
         JOIN course c ON c.id = tt.course_id
         JOIN time_slot ts ON ts.id = ai.time_slot_id
         WHERE (c.course_type IN ('理论课', '实践课') AND ts.period_index NOT IN (1, 3, 5, 7, 9))
            OR (c.course_type IN ('上机课', '实验课') AND ts.period_index NOT IN (1, 5)))
        +
        (SELECT COUNT(*)
         FROM course_assignment ca
         JOIN teaching_task tt ON tt.id = ca.teaching_task_id
         JOIN course c ON c.id = tt.course_id
         JOIN time_slot ts ON ts.id = ca.time_slot_id
         WHERE (c.course_type IN ('理论课', '实践课') AND ts.period_index NOT IN (1, 3, 5, 7, 9))
            OR (c.course_type IN ('上机课', '实验课') AND ts.period_index NOT IN (1, 5)))
    INTO invalid_session_block_count;

    IF invalid_coordinate_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '003 migration blocked: time_slot contains coordinates outside periods 1..10';
    END IF;

    IF invalid_session_block_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '003 migration blocked: legacy assignment starts cannot be safely converted to 2/4-slot sessions';
    END IF;
END//
DELIMITER ;

CALL assert_atomic_time_axis_migration();
DROP PROCEDURE assert_atomic_time_axis_migration;
