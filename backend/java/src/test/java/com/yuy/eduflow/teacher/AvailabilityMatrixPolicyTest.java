package com.yuy.eduflow.teacher;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.yuy.eduflow.common.exception.ValidationException;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class AvailabilityMatrixPolicyTest {

	private final ObjectMapper objectMapper = new ObjectMapper();

	@Test
	void expandsTheLegacyFiveBlockMatrixIntoElevenAtomicPeriods() throws Exception {
		String legacy = "[[1,0,0,0,0,0,0],[0,1,0,0,0,0,0],[0,0,1,0,0,0,0],[0,0,0,1,0,0,0],[-1,-1,-1,-1,-1,-1,-1]]";

		String normalized = AvailabilityMatrixPolicy.normalize(objectMapper, legacy);
		List<?> rows = objectMapper.readValue(normalized, List.class);

		// 前四个大块各两节，晚间大块是三节：2*4 + 3 = 11。
		assertEquals(11, rows.size());
		assertEquals(rows.get(0), rows.get(1));
		assertEquals(rows.get(8), rows.get(9));
		assertEquals(rows.get(9), rows.get(10));
	}

	@Test
	void extendsATenPeriodMatrixByRepeatingTheEveningValue() throws Exception {
		StringBuilder legacy = new StringBuilder("[");
		for (int period = 1; period <= 10; period++) {
			legacy.append(period == 10 ? "[-1,-1,-1,-1,-1,-1,-1]" : "[0,0,0,0,0,0,0]");
			if (period < 10) {
				legacy.append(',');
			}
		}
		legacy.append(']');

		String normalized = AvailabilityMatrixPolicy.normalize(objectMapper, legacy.toString());
		List<?> rows = objectMapper.readValue(normalized, List.class);

		assertEquals(11, rows.size());
		assertEquals(rows.get(9), rows.get(10), "第11节应沿用第10节的晚间取值，而不是凭空放开");
	}

	@Test
	void rejectsASevenColumnMatrixWithTheWrongPeriodCount() {
		String invalid = "[[0,0,0,0,0,0,0]]";

		assertThrows(ValidationException.class, () -> AvailabilityMatrixPolicy.normalize(objectMapper, invalid));
	}
}
