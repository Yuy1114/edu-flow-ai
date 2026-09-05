package com.yuy.eduflow.timeslot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class TeachingSessionTimePolicyTest {

	@Test
	void theoryUsesAlignedTwoPeriodBlocksIncludingEvening() {
		assertEquals(2, TeachingSessionTimePolicy.periodCount("理论课"));
		assertTrue(TeachingSessionTimePolicy.isLegalStartPeriod(9, 2));
		assertEquals(List.of(9, 10), TeachingSessionTimePolicy.occupiedPeriods(9, 2));
		assertFalse(TeachingSessionTimePolicy.isLegalStartPeriod(4, 2));
	}

	@Test
	void labUsesWholeMorningOrWholeAfternoonOnly() {
		assertEquals(4, TeachingSessionTimePolicy.periodCount("上机课"));
		assertEquals(4, TeachingSessionTimePolicy.periodCount("实验课"));
		assertEquals(List.of(5, 6, 7, 8), TeachingSessionTimePolicy.occupiedPeriods(5, 4));
		assertFalse(TeachingSessionTimePolicy.isLegalStartPeriod(7, 4));
		assertFalse(TeachingSessionTimePolicy.isLegalStartPeriod(9, 4));
	}

	@Test
	void unknownCourseTypeMustNotSilentlyAssumeASpan() {
		assertEquals(0, TeachingSessionTimePolicy.periodCount(null));
		assertEquals(0, TeachingSessionTimePolicy.periodCount("其他"));
	}
}
