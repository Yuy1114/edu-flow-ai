-- Old docker-entrypoint runs could parse Chinese ENUM literals through a
-- latin1 client even though the table charset was utf8mb4. Rebuild the three
-- room-type columns through UTF-8 temporary columns. Values are preserved by
-- ENUM ordinal, so this repairs both correctly encoded and mojibake schemas.
USE edu_flow_ai;
SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS normalize_room_type_enum;
DELIMITER //
CREATE PROCEDURE normalize_room_type_enum(
    IN p_table_name VARCHAR(64),
    IN p_column_name VARCHAR(64),
    IN p_comment VARCHAR(255)
)
BEGIN
    DECLARE old_exists INT DEFAULT 0;
    DECLARE temp_exists INT DEFAULT 0;
    DECLARE temp_column VARCHAR(80);
    SET temp_column = CONCAT(p_column_name, '__utf8_v2');

    SELECT COUNT(*) INTO old_exists
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name;

    SELECT COUNT(*) INTO temp_exists
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = temp_column;

    IF temp_exists = 0 THEN
        SET @ddl = CONCAT(
            'ALTER TABLE `', p_table_name, '` ADD COLUMN `', temp_column,
            '` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL'
        );
        PREPARE statement FROM @ddl;
        EXECUTE statement;
        DEALLOCATE PREPARE statement;
        SET temp_exists = 1;
    END IF;

    IF old_exists = 1 THEN
        SET @ddl = CONCAT(
            'UPDATE `', p_table_name, '` SET `', temp_column,
            '` = CASE (`', p_column_name, '` + 0)',
            ' WHEN 1 THEN ''普通教室'' WHEN 2 THEN ''机房'' ELSE NULL END'
        );
        PREPARE statement FROM @ddl;
        EXECUTE statement;
        DEALLOCATE PREPARE statement;

        SET @ddl = CONCAT(
            'ALTER TABLE `', p_table_name, '` DROP COLUMN `', p_column_name, '`'
        );
        PREPARE statement FROM @ddl;
        EXECUTE statement;
        DEALLOCATE PREPARE statement;
        SET old_exists = 0;
    END IF;

    IF old_exists = 0 AND temp_exists = 1 THEN
        SET @ddl = CONCAT(
            'ALTER TABLE `', p_table_name, '` CHANGE COLUMN `', temp_column,
            '` `', p_column_name,
            '` ENUM(''普通教室'',''机房'') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL COMMENT ',
            QUOTE(p_comment)
        );
        PREPARE statement FROM @ddl;
        EXECUTE statement;
        DEALLOCATE PREPARE statement;
    END IF;
END//
DELIMITER ;

CALL normalize_room_type_enum('course', 'required_room_type', '所需教室类型：普通教室 / 机房（实践课为NULL）');
CALL normalize_room_type_enum('classroom', 'classroom_type', '教室物理类型');
CALL normalize_room_type_enum('teaching_task', 'required_room_type', '教学任务所需教室类型，从 course.required_room_type 继承或覆写');

DROP PROCEDURE normalize_room_type_enum;
