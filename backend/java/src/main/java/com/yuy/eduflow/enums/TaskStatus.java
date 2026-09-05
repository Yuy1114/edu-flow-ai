package com.yuy.eduflow.enums;

import com.yuy.eduflow.common.exception.ValidationException;

/**
 * 分课任务状态。
 * 适用于：allocation_task（分课任务）。
 */
public enum TaskStatus implements CodeEnum {
	CREATED("CREATED", "已创建"),
	RUNNING("RUNNING", "排课中"),
	GENERATED("GENERATED", "已生成候选方案"),
	NEEDS_MANUAL_REVIEW("NEEDS_MANUAL_REVIEW", "需要人工复核"),
	BLOCKED("BLOCKED", "存在硬约束阻塞"),
	FAILED("FAILED", "生成失败"),
	CANCELLED("CANCELLED", "已取消"),
	DRAFT("DRAFT", "草稿"),
	PENDING("PENDING", "待处理"),
	CONFIRMED("CONFIRMED", "已确认"),
	REJECTED("REJECTED", "已拒绝");

	private final String code;
	private final String label;

	TaskStatus(String code, String label) {
		this.code = code;
		this.label = label;
	}

	public String code() {
		return code;
	}

	public String label() {
		return label;
	}

	public static TaskStatus from(String code) {
		if (code == null || code.isBlank()) {
			return null;
		}
		for (TaskStatus status : values()) {
			if (status.code.equalsIgnoreCase(code.trim())) {
				return status;
			}
		}
		throw new ValidationException("未知分课任务状态: " + code);
	}
}
