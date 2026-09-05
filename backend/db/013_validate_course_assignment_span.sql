-- Close the forward-migration gap left by migrations 005/012.
--
-- The application permits a one-period manual correction for every supported
-- course type.  Normal theory/practice sessions occupy two periods and normal
-- computer/experiment sessions occupy four.  Existing published data must
-- satisfy both that type contract and the 4+4+2 timetable block boundaries
-- before the storage-level CHECK is tightened.
--
-- Deliberately no hard-coded USE statement: migrate.sh selects DB_NAME before
-- executing this immutable migration.
SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS assert_course_assignment_span_contract;
DELIMITER //
CREATE PROCEDURE assert_course_assignment_span_contract()
BEGIN
    DECLARE invalid_span_count BIGINT DEFAULT 0;
    DECLARE invalid_course_contract_count BIGINT DEFAULT 0;
    DECLARE invalid_start_or_boundary_count BIGINT DEFAULT 0;

    SELECT COUNT(*) INTO invalid_span_count
    FROM course_assignment ca
    WHERE ca.consecutive_slots IS NULL
       OR ca.consecutive_slots NOT IN (1, 2, 4);

    SELECT COUNT(*) INTO invalid_course_contract_count
    FROM course_assignment ca
    LEFT JOIN teaching_task tt ON tt.id = ca.teaching_task_id
    LEFT JOIN course c ON c.id = tt.course_id
    WHERE c.id IS NULL
       OR c.course_type IS NULL
       OR c.course_type NOT IN ('理论课', '实践课', '上机课', '实验课')
       OR (
            ca.consecutive_slots <> 1
            AND (
                (c.course_type IN ('理论课', '实践课') AND ca.consecutive_slots <> 2)
                OR (c.course_type IN ('上机课', '实验课') AND ca.consecutive_slots <> 4)
            )
       );

    SELECT COUNT(*) INTO invalid_start_or_boundary_count
    FROM course_assignment ca
    LEFT JOIN time_slot ts ON ts.id = ca.time_slot_id
    WHERE ts.id IS NULL
       OR ts.period_index NOT BETWEEN 1 AND 10
       OR (ca.consecutive_slots = 2 AND ts.period_index NOT IN (1, 3, 5, 7, 9))
       OR (ca.consecutive_slots = 4 AND ts.period_index NOT IN (1, 5))
       OR ts.period_index + ca.consecutive_slots - 1 > CASE
            WHEN ts.period_index BETWEEN 1 AND 4 THEN 4
            WHEN ts.period_index BETWEEN 5 AND 8 THEN 8
            WHEN ts.period_index BETWEEN 9 AND 10 THEN 10
            ELSE 0
          END;

    IF invalid_span_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '013 migration blocked: course_assignment consecutive_slots must be 1, 2, or 4';
    END IF;

    IF invalid_course_contract_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '013 migration blocked: assignment span does not match its course type';
    END IF;

    IF invalid_start_or_boundary_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '013 migration blocked: assignment start/span crosses a 4+4+2 timetable block';
    END IF;
END//
DELIMITER ;

CALL assert_course_assignment_span_contract();
DROP PROCEDURE assert_course_assignment_span_contract;

-- Replace the permissive 1..10 legacy check.  Cross-table course-type and
-- start-slot rules are enforced by the publication service; this CHECK still
-- prevents every writer from persisting an unsupported span length.
SET @drop_span_check := IF(
    EXISTS(
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE()
          AND table_name = 'course_assignment'
          AND constraint_name = 'chk_course_assignment_consecutive_slots'
          AND constraint_type = 'CHECK'
    ),
    'ALTER TABLE course_assignment DROP CHECK chk_course_assignment_consecutive_slots',
    'SELECT 1'
);
PREPARE statement FROM @drop_span_check;
EXECUTE statement;
DEALLOCATE PREPARE statement;

ALTER TABLE course_assignment
    ADD CONSTRAINT chk_course_assignment_consecutive_slots
    CHECK (consecutive_slots IN (1, 2, 4));
