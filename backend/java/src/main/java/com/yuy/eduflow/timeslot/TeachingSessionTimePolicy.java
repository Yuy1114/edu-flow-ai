package com.yuy.eduflow.timeslot;

import java.util.List;
import java.util.Set;
import java.util.stream.IntStream;

/**
 * 旧版 {@code allocation_item}/{@code course_assignment} 只保存一次课的起始时间片。
 * 本策略是该存储模型下唯一的占用跨度契约：理论/实践课占连续 2 个原子节次，
 * 上机/实验课占连续 4 个原子节次。
 */
public final class TeachingSessionTimePolicy {
	public static final int THEORY_PERIODS = 2;
	public static final int LAB_PERIODS = 4;

	private static final Set<String> TWO_PERIOD_TYPES = Set.of("理论课", "实践课");
	private static final Set<String> FOUR_PERIOD_TYPES = Set.of("上机课", "实验课");
	private static final Set<Integer> TWO_PERIOD_STARTS = Set.of(1, 3, 5, 7, 9);
	private static final Set<Integer> FOUR_PERIOD_STARTS = Set.of(1, 5);

	private TeachingSessionTimePolicy() {
	}

	/** 返回课程一次课占用的原子节次数；未知类型返回 0，由调用方显式拒绝。 */
	public static int periodCount(String courseType) {
		String normalized = courseType == null ? "" : courseType.trim();
		if (TWO_PERIOD_TYPES.contains(normalized)) {
			return THEORY_PERIODS;
		}
		if (FOUR_PERIOD_TYPES.contains(normalized)) {
			return LAB_PERIODS;
		}
		return 0;
	}

	/**
	 * 合法块不能跨上午(1-4)、下午(5-8)、晚上(9-10)边界。
	 * 因而 2 节块只能从 1/3/5/7/9 开始，4 节块只能从 1/5 开始。
	 */
	public static boolean isLegalStartPeriod(int startPeriod, int periodCount) {
		return switch (periodCount) {
			case THEORY_PERIODS -> TWO_PERIOD_STARTS.contains(startPeriod);
			case LAB_PERIODS -> FOUR_PERIOD_STARTS.contains(startPeriod);
			default -> false;
		};
	}

	public static List<Integer> occupiedPeriods(int startPeriod, int periodCount) {
		if (!isLegalStartPeriod(startPeriod, periodCount)) {
			return List.of();
		}
		return IntStream.range(startPeriod, startPeriod + periodCount).boxed().toList();
	}

	public static String legalStartDescription(int periodCount) {
		return periodCount == LAB_PERIODS ? "1或5" : "1、3、5、7或9";
	}
}
