package com.yuy.eduflow.timeslot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class SchedulingTimePolicyTest {

	@Test
	void exposesTenAtomicPeriodsAndKeepsEveningOutOfTheAutomaticDefault() {
		assertEquals(45, SchedulingTimePolicy.PERIOD_MINUTES);
		assertEquals(11, SchedulingTimePolicy.LAST_PERIOD);
		assertEquals("1,2,3,4,5,6,7,8", SchedulingTimePolicy.DEFAULT_AUTOMATIC_PERIODS);
		assertFalse(SchedulingTimePolicy.isEvening(8));
		assertTrue(SchedulingTimePolicy.isEvening(9));
		assertTrue(SchedulingTimePolicy.isEvening(10));
	}
}
