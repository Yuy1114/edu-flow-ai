package com.yuy.eduflow.timeslot;

import java.util.stream.Collectors;
import java.util.stream.IntStream;

/**
 * 全系统时间坐标：每天 10 个 45 分钟原子节次，按上午 4 节、下午 4 节、晚上 2 节划分。
 * 自动排课默认只使用工作日第 1-8 节；第 9-10 节和周末仍保留为合法时间片，供人工调课使用。
 */
public final class SchedulingTimePolicy {
	public static final int PERIOD_MINUTES = 45;
	public static final int FIRST_WEEK = 1;
	public static final int LAST_WEEK = 18;
	public static final int FIRST_PERIOD = 1;
	public static final int MORNING_LAST_PERIOD = 4;
	public static final int AFTERNOON_LAST_PERIOD = 8;
	public static final int EVENING_FIRST_PERIOD = 9;
	public static final int LAST_PERIOD = 10;
	public static final int WEEKDAY_FIRST = 1;
	public static final int WEEKDAY_LAST = 5;
	public static final int DAYS_PER_WEEK = 7;
	public static final String DEFAULT_AUTOMATIC_PERIODS = csvRange(FIRST_PERIOD, AFTERNOON_LAST_PERIOD);

	private SchedulingTimePolicy() {
	}

	public static boolean isEvening(int periodIndex) {
		return periodIndex >= EVENING_FIRST_PERIOD && periodIndex <= LAST_PERIOD;
	}

	private static String csvRange(int startInclusive, int endInclusive) {
		return IntStream.rangeClosed(startInclusive, endInclusive)
			.mapToObj(String::valueOf)
			.collect(Collectors.joining(","));
	}
}
