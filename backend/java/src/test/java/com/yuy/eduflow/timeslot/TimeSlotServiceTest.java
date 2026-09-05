package com.yuy.eduflow.timeslot;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.yuy.eduflow.common.exception.ValidationException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class TimeSlotServiceTest {

	@Mock
	private TimeSlotMapper timeSlotMapper;

	private TimeSlotService service;

	@BeforeEach
	void setUp() {
		service = new TimeSlotService(timeSlotMapper);
	}

	@Test
	void rejectsRuntimeCreateBecauseTheCanonicalCatalogIsMigrationOwned() {
		assertThrows(
			ValidationException.class,
			() -> service.create(new TimeSlotRequest(1, 7, 10, "第1周 周日 第10节"))
		);

		verify(timeSlotMapper, never()).insert(org.mockito.ArgumentMatchers.any());
	}

	@Test
	void rejectsRuntimeUpdateAndDeleteWithoutTouchingTheCatalog() {
		assertThrows(ValidationException.class, () -> service.update(1L, new TimeSlotRequest(1, 1, 1, "篡改")));
		assertThrows(ValidationException.class, () -> service.delete(1L));

		verify(timeSlotMapper, never()).update(org.mockito.ArgumentMatchers.any());
		verify(timeSlotMapper, never()).delete(1L);
	}
}
