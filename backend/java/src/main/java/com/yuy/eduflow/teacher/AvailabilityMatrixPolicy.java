package com.yuy.eduflow.teacher;

import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.timeslot.SchedulingTimePolicy;
import java.util.ArrayList;
import java.util.List;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

/** Normalizes teacher availability to matrix[period-1][weekday-1], 11 x 7. */
public final class AvailabilityMatrixPolicy {
	public static final int PERIOD_ROWS = SchedulingTimePolicy.LAST_PERIOD;
	public static final int WEEKDAY_COLUMNS = SchedulingTimePolicy.DAYS_PER_WEEK;
	private static final int LEGACY_BLOCK_ROWS = 5;
	private static final int LEGACY_TEN_PERIOD_ROWS = 10;
	private static final int EVENING_PERIODS =
		SchedulingTimePolicy.LAST_PERIOD - SchedulingTimePolicy.EVENING_FIRST_PERIOD + 1;

	private AvailabilityMatrixPolicy() {
	}

	public static String normalize(ObjectMapper objectMapper, String rawJson) {
		if (!StringUtils.hasText(rawJson)) {
			return null;
		}
		try {
			Object decoded = objectMapper.readValue(rawJson, Object.class);
			if (!(decoded instanceof List<?> rawRows)) {
				throw invalidShape();
			}
			List<List<Integer>> rows = validateRows(rawRows);
			if (rows.size() == LEGACY_BLOCK_ROWS) {
				// 旧的五大块矩阵：前四块各是两节，最后一块是晚间的三节。
				List<List<Integer>> expanded = new ArrayList<>(PERIOD_ROWS);
				for (int block = 0; block < rows.size(); block++) {
					int periodsInBlock = block == rows.size() - 1 ? EVENING_PERIODS : 2;
					for (int repeat = 0; repeat < periodsInBlock; repeat++) {
						expanded.add(new ArrayList<>(rows.get(block)));
					}
				}
				rows = expanded;
			} else if (rows.size() == LEGACY_TEN_PERIOD_ROWS) {
				// 旧的 10 节矩阵：第 11 节沿用第 10 节的晚间取值，不凭空填 0。
				rows = new ArrayList<>(rows);
				rows.add(new ArrayList<>(rows.get(LEGACY_TEN_PERIOD_ROWS - 1)));
			}
			if (rows.size() != PERIOD_ROWS) {
				throw invalidShape();
			}
			return objectMapper.writeValueAsString(rows);
		} catch (ValidationException exception) {
			throw exception;
		} catch (Exception exception) {
			throw new ValidationException("固定周可用性矩阵必须是合法 JSON，结构为11行×7列");
		}
	}

	/**
	 * Returns whether an atomic timetable coordinate is explicitly forbidden by the
	 * teacher's fixed availability matrix. A missing matrix means unrestricted.
	 */
	public static boolean isHardUnavailable(
		ObjectMapper objectMapper,
		String rawJson,
		int dayOfWeek,
		int periodIndex
	) {
		if (dayOfWeek < 1 || dayOfWeek > WEEKDAY_COLUMNS
			|| periodIndex < 1 || periodIndex > PERIOD_ROWS) {
			throw new ValidationException("教师可用性检查坐标必须为周一至周日、第1至11节");
		}
		String normalized = normalize(objectMapper, rawJson);
		if (normalized == null) {
			return false;
		}
		try {
			Object decoded = objectMapper.readValue(normalized, Object.class);
			List<?> rows = (List<?>) decoded;
			List<?> row = (List<?>) rows.get(periodIndex - 1);
			return ((Number) row.get(dayOfWeek - 1)).intValue() == -1;
		} catch (Exception exception) {
			throw new ValidationException("固定周可用性矩阵必须是合法 JSON，结构为11行×7列");
		}
	}

	private static List<List<Integer>> validateRows(List<?> rawRows) {
		if (rawRows.size() != LEGACY_BLOCK_ROWS
			&& rawRows.size() != LEGACY_TEN_PERIOD_ROWS
			&& rawRows.size() != PERIOD_ROWS) {
			throw invalidShape();
		}
		List<List<Integer>> rows = new ArrayList<>(rawRows.size());
		for (Object rawRow : rawRows) {
			if (!(rawRow instanceof List<?> cells) || cells.size() != WEEKDAY_COLUMNS) {
				throw invalidShape();
			}
			List<Integer> row = new ArrayList<>(WEEKDAY_COLUMNS);
			for (Object cell : cells) {
				if (!(cell instanceof Number number)) {
					throw new ValidationException("固定周可用性矩阵只允许 -1、0、1");
				}
				int value = number.intValue();
				if (number.doubleValue() != value || value < -1 || value > 1) {
					throw new ValidationException("固定周可用性矩阵只允许 -1、0、1");
				}
				row.add(value);
			}
			rows.add(row);
		}
		return rows;
	}

	private static ValidationException invalidShape() {
		return new ValidationException("固定周可用性矩阵必须为11行×7列（兼容旧的5行×7列与10行×7列并自动展开）");
	}
}
