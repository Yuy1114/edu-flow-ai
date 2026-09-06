-- 把每天的原子节次从 10 节扩到 11 节（上午 1-4、下午 5-8、晚上 9-11）。
--
-- 依据：真实课表表尾的作息说明「晚上9-11节：19：10-21：35」。学校晚上是一个
-- 三节的大块（145 分钟），而不是两节。原来的 10 节坐标装不下第 11 节，
-- 导致真实晚间课程无处安放。
--
-- 迁移约束：
-- 1. 只 INSERT 第 11 节的新坐标，不改动任何既有行，因此 time_slot.id 及其
--    全部外键引用（course_assignment.time_slot_id 等）保持不变。
-- 2. 自动排课域不变，仍是工作日第 1-8 节；第 9-11 节和周末都是人工保留时段。
-- 3. 003 与 012 中「1..10」的校验属于当时的历史口径，已应用的库不会重放，
--    新库的执行顺序是 003 → 012 → 013 → 014，因此不冲突。
-- 4. 可重复执行：INSERT ... SELECT ... WHERE NOT EXISTS。

SET NAMES utf8mb4;

INSERT INTO time_slot (week_number, day_of_week, period_index, label)
SELECT weeks.week_number,
       weekdays.day_of_week,
       11,
       CONCAT('第', weeks.week_number, '周 周', weekdays.day_of_week, ' 第11节')
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
WHERE NOT EXISTS (
    SELECT 1 FROM time_slot existing
    WHERE existing.week_number = weeks.week_number
      AND existing.day_of_week = weekdays.day_of_week
      AND existing.period_index = 11
);

-- 教师可用性矩阵补第 11 行。第 9、10 节都来自旧的第 5 大块，晚间语义相同，
-- 因此第 11 节沿用第 10 节的取值，而不是凭空填 0。
UPDATE teacher_profile
SET availability_matrix_json = JSON_ARRAY_APPEND(
    availability_matrix_json, '$', JSON_EXTRACT(availability_matrix_json, '$[9]')
)
WHERE availability_matrix_json IS NOT NULL
  AND JSON_VALID(availability_matrix_json)
  AND JSON_TYPE(JSON_EXTRACT(availability_matrix_json, '$')) = 'ARRAY'
  AND JSON_LENGTH(availability_matrix_json) = 10;

ALTER TABLE time_slot
    MODIFY period_index INT NOT NULL COMMENT '45分钟原子节次，1-4上午、5-8下午、9-11晚上';

ALTER TABLE teacher_profile
    MODIFY availability_matrix_json TEXT NULL
    COMMENT '教师固定周可用性矩阵 JSON，11x7，matrix[period-1][weekday-1]，每节45分钟，-1不可用/0随意/1明确可用';

ALTER TABLE allocation_task_generation_config
    MODIFY allowed_periods VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5,6,7,8'
    COMMENT '允许自动排课的45分钟原子节次；默认1-8，第9-11节保留给人工调课',
    MODIFY late_period_penalty DECIMAL(10,6) NOT NULL DEFAULT 0.030000
    COMMENT '晚课惩罚（第9-11节）';

-- 执行后应得到 18 * 7 * 11 = 1386 个标准坐标。
SELECT COUNT(*) AS canonical_time_slot_count
FROM time_slot
WHERE week_number BETWEEN 1 AND 18
  AND day_of_week BETWEEN 1 AND 7
  AND period_index BETWEEN 1 AND 11;

SELECT COUNT(*) AS invalid_period_count
FROM time_slot
WHERE period_index NOT BETWEEN 1 AND 11;
