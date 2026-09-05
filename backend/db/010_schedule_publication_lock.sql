-- Singleton row used as a transaction-level global publication mutex.
USE edu_flow_ai;

CREATE TABLE IF NOT EXISTS schedule_publication_lock (
    id TINYINT PRIMARY KEY,
    lock_name VARCHAR(64) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_schedule_publication_lock_name (lock_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO schedule_publication_lock (id, lock_name)
VALUES (1, 'GLOBAL_SCHEDULE_PUBLICATION')
ON DUPLICATE KEY UPDATE lock_name = VALUES(lock_name);
