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
	void expandsTheLegacyFiveBlockMatrixIntoTenAtomicPeriods() throws Exception {
		String legacy = "[[1,0,0,0,0,0,0],[0,1,0,0,0,0,0],[0,0,1,0,0,0,0],[0,0,0,1,0,0,0],[-1,-1,-1,-1,-1,-1,-1]]";

		String normalized = AvailabilityMatrixPolicy.normalize(objectMapper, legacy);
		List<?> rows = objectMapper.readValue(normalized, List.class);

		assertEquals(10, rows.size());
		assertEquals(rows.get(0), rows.get(1));
		assertEquals(rows.get(8), rows.get(9));
	}

	@Test
	void rejectsASevenColumnMatrixWithTheWrongPeriodCount() {
		String invalid = "[[0,0,0,0,0,0,0]]";

		assertThrows(ValidationException.class, () -> AvailabilityMatrixPolicy.normalize(objectMapper, invalid));
	}
}
