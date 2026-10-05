-- Add teacher profile explanation fields to allocation_item.
-- Use this when upgrading an existing local/dev database whose schema was created before Phase 3.

ALTER TABLE allocation_item
    ADD COLUMN teacher_profile_score DOUBLE NULL COMMENT '教师画像满足度分数 0-1' AFTER time_slot_id,
    ADD COLUMN teacher_profile_penalty DOUBLE NULL COMMENT '教师画像软惩罚 0-1' AFTER teacher_profile_score,
    ADD COLUMN teacher_profile_reasons_json TEXT NULL COMMENT '教师画像解释原因 JSON 数组' AFTER teacher_profile_penalty,
    ADD COLUMN teacher_profile_components_json TEXT NULL COMMENT '教师画像分项满足度 JSON' AFTER teacher_profile_reasons_json;
