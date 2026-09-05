-- Persist the actual atomic span of every published teaching session.
-- Legacy rows had no span, so their only recoverable default is 2 slots for
-- theory/practice and 4 slots for computer/experiment courses. New manual
-- assignments may explicitly use one 45-minute slot.
USE edu_flow_ai;
SET NAMES utf8mb4;

SET @consecutive_slots_column_existed := (
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'course_assignment' AND column_name = 'consecutive_slots'
    )
);

SET @ddl := IF(
    @consecutive_slots_column_existed = 1,
    'SELECT 1',
    'ALTER TABLE course_assignment ADD COLUMN consecutive_slots INT NULL COMMENT ''本次授课实际占用的45分钟原子节数；人工补课可为1'' AFTER time_slot_id'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;

-- A legacy row only recorded its start slot.  Inferring four slots for an old
-- lab/computer row that starts at period 3/7/9 would silently cross a
-- morning/afternoon/evening boundary.  Stop and require an explicit human
-- decision instead of publishing a fabricated span.
DROP PROCEDURE IF EXISTS assert_legacy_assignment_span_inference;
DELIMITER //
CREATE PROCEDURE assert_legacy_assignment_span_inference()
BEGIN
    DECLARE unsafe_inference_count BIGINT DEFAULT 0;

    SELECT COUNT(*) INTO unsafe_inference_count
    FROM course_assignment ca
    JOIN teaching_task tt ON tt.id = ca.teaching_task_id
    JOIN course c ON c.id = tt.course_id
    JOIN time_slot ts ON ts.id = ca.time_slot_id
    WHERE (
        @consecutive_slots_column_existed = 0
        OR ca.consecutive_slots IS NULL
        OR ca.consecutive_slots NOT BETWEEN 1 AND 10
    )
      AND (
        (c.course_type IN ('上机课', '实验课') AND ts.period_index NOT IN (1, 5))
        OR (c.course_type IN ('理论课', '实践课') AND ts.period_index NOT IN (1, 3, 5, 7, 9))
      );

    IF unsafe_inference_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '005 migration blocked: legacy course_assignment span cannot be inferred safely from its start slot';
    END IF;
END//
DELIMITER ;

CALL assert_legacy_assignment_span_inference();
DROP PROCEDURE assert_legacy_assignment_span_inference;

UPDATE course_assignment ca
JOIN teaching_task tt ON tt.id = ca.teaching_task_id
JOIN course c ON c.id = tt.course_id
SET ca.consecutive_slots = CASE
    WHEN c.course_type IN ('上机课', '实验课') THEN 4
    ELSE 2
END
WHERE @consecutive_slots_column_existed = 0
   OR ca.consecutive_slots IS NULL
   OR ca.consecutive_slots NOT BETWEEN 1 AND 10;

ALTER TABLE course_assignment
    MODIFY consecutive_slots INT NOT NULL DEFAULT 2
    COMMENT '本次授课实际占用的45分钟原子节数；人工补课可为1';

SET @ddl := IF(
    EXISTS(
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE()
          AND table_name = 'course_assignment'
          AND constraint_name = 'chk_course_assignment_consecutive_slots'
    ),
    'SELECT 1',
    'ALTER TABLE course_assignment ADD CONSTRAINT chk_course_assignment_consecutive_slots CHECK (consecutive_slots BETWEEN 1 AND 10)'
);
PREPARE statement FROM @ddl;
EXECUTE statement;
DEALLOCATE PREPARE statement;
