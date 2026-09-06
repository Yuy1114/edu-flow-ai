package com.yuy.eduflow.export;

import com.yuy.eduflow.common.exception.ValidationException;

/** 课表导出的角色视角。每个角色决定按谁分表，以及格子里省略哪一维。 */
public enum TimetableExportRole {
	TEACHER("教师课表"),
	CLASS("班级课表"),
	CLASSROOM("教室占用表"),
	REGISTRAR("教务总表");

	private final String label;

	TimetableExportRole(String label) {
		this.label = label;
	}

	public String label() {
		return label;
	}

	public static TimetableExportRole from(String raw) {
		if (raw == null || raw.isBlank()) {
			throw new ValidationException("导出角色不能为空：可选 TEACHER、CLASS、CLASSROOM、REGISTRAR");
		}
		try {
			return valueOf(raw.trim().toUpperCase());
		} catch (IllegalArgumentException ex) {
			throw new ValidationException("不支持的导出角色：" + raw + "；可选 TEACHER、CLASS、CLASSROOM、REGISTRAR");
		}
	}
}
