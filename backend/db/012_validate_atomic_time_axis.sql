-- Forward safety net for volumes that previously recorded migrations 003/005
-- with the non-resumable implementations.  This migration never guesses an
-- ambiguous published session: it repairs the unambiguous 101..105 staging
-- coordinates, then fails closed if a stored span crosses a timetable block.
USE edu_flow_ai;
SET NAMES utf8mb4;

START TRANSACTION;
UPDATE time_slot
SET period_index = CASE period_index
    WHEN 101 THEN 1
    WHEN 102 THEN 3
    WHEN 103 THEN 5
    WHEN 104 THEN 7
    WHEN 105 THEN 9
    ELSE period_index
END
WHERE period_index BETWEEN 101 AND 105;
COMMIT;

DROP PROCEDURE IF EXISTS assert_atomic_time_axis_and_assignment_spans;
DELIMITER //
CREATE PROCEDURE assert_atomic_time_axis_and_assignment_spans()
BEGIN
    DECLARE invalid_coordinate_count BIGINT DEFAULT 0;
    DECLARE unsafe_assignment_count BIGINT DEFAULT 0;

    SELECT COUNT(*) INTO invalid_coordinate_count
    FROM time_slot
    WHERE period_index NOT BETWEEN 1 AND 10;

    SELECT COUNT(*) INTO unsafe_assignment_count
    FROM course_assignment ca
    JOIN time_slot ts ON ts.id = ca.time_slot_id
    WHERE ts.period_index + ca.consecutive_slots - 1 > 10
       OR (ca.consecutive_slots = 2 AND ts.period_index NOT IN (1, 3, 5, 7, 9))
       OR (ca.consecutive_slots = 4 AND ts.period_index NOT IN (1, 5));

    IF invalid_coordinate_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '012 migration blocked: time_slot contains coordinates outside periods 1..10';
    END IF;

    IF unsafe_assignment_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '012 migration blocked: published assignment span crosses an atomic timetable block';
    END IF;
END//
DELIMITER ;

CALL assert_atomic_time_axis_and_assignment_spans();
DROP PROCEDURE assert_atomic_time_axis_and_assignment_spans;
