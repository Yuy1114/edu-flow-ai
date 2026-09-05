package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.enums.TaskStatus;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AllocationTaskServiceTimePolicyTest {

	@Mock
	private AllocationTaskMapper allocationTaskMapper;
	@Mock
	private AllocationTaskGenerationConfigMapper generationConfigMapper;

	private AllocationTaskService service;

	@BeforeEach
	void setUp() {
		service = new AllocationTaskService(allocationTaskMapper, generationConfigMapper);
	}

	@Test
	void defaultsAutomaticSchedulingToPeriodsOneThroughEight() {
		stubTaskInsert();
		service.create(new AllocationTaskRequest("2026秋季排课", null, null, null, List.of(), null));

		ArgumentCaptor<AllocationTaskGenerationConfig> captor = ArgumentCaptor.forClass(AllocationTaskGenerationConfig.class);
		verify(generationConfigMapper).insert(captor.capture());
		assertEquals("1,2,3,4,5,6,7,8", captor.getValue().getAllowedPeriods());
	}

	@Test
	void permitsEveningPeriodsWhenAnOperatorExplicitlyEnablesThem() {
		stubTaskInsert();
		service.create(new AllocationTaskRequest("人工晚间排课", null, null, null, List.of(), config("9,10")));

		ArgumentCaptor<AllocationTaskGenerationConfig> captor = ArgumentCaptor.forClass(AllocationTaskGenerationConfig.class);
		verify(generationConfigMapper).insert(captor.capture());
		assertEquals("9,10", captor.getValue().getAllowedPeriods());
	}

	@Test
	void rejectsAnEleventhPeriod() {
		assertThrows(
			ValidationException.class,
			() -> service.create(new AllocationTaskRequest("非法节次", null, null, null, List.of(), config("11")))
		);
		verify(generationConfigMapper, never()).insert(any());
	}

	@Test
	void generatedTasksCannotBeOrdinarilyUpdatedOrDeleted() {
		AllocationTask generated = new AllocationTask();
		generated.setId(7L);
		generated.setStatus(TaskStatus.GENERATED);
		when(allocationTaskMapper.findByIdForUpdate(7L)).thenReturn(generated);

		assertThrows(ValidationException.class, () -> service.update(
			7L, new AllocationTaskRequest("篡改", null, null, null, List.of(), null)
		));
		assertThrows(ValidationException.class, () -> service.delete(7L));

		verify(allocationTaskMapper, never()).update(any());
		verify(allocationTaskMapper, never()).deleteById(7L);
	}

	@Test
	void confirmedTasksCannotBeRegeneratedAndGenerationPreflightDoesNotWriteRunning() {
		AllocationTask confirmed = new AllocationTask();
		confirmed.setId(7L);
		confirmed.setStatus(TaskStatus.CONFIRMED);
		when(allocationTaskMapper.findByIdForUpdate(7L)).thenReturn(confirmed);
		assertThrows(ValidationException.class, () -> service.validateGenerationAllowed(7L));

		AllocationTask created = new AllocationTask();
		created.setId(8L);
		created.setStatus(TaskStatus.CREATED);
		when(allocationTaskMapper.findByIdForUpdate(8L)).thenReturn(created);
		when(allocationTaskMapper.countSchemesByTaskId(8L)).thenReturn(0);
		service.validateGenerationAllowed(8L);

		verify(allocationTaskMapper, never()).updateStatus(any(), any());
		verify(allocationTaskMapper, never()).updateStatusIfCurrent(any(), any(), any());
	}

	@Test
	void blockedTasksCanBeCorrectedAndRetriedWhenNoCandidateWasPublished() {
		AllocationTask blocked = new AllocationTask();
		blocked.setId(9L);
		blocked.setName("待修正任务");
		blocked.setStatus(TaskStatus.BLOCKED);
		when(allocationTaskMapper.findByIdForUpdate(9L)).thenReturn(blocked);
		when(allocationTaskMapper.countSchemesByTaskId(9L)).thenReturn(0);

		service.update(
			9L,
			new AllocationTaskRequest("已修正任务", null, null, null, List.of(), config("1,2,3,4,5,6,7,8"))
		);
		service.validateGenerationAllowed(9L);

		verify(allocationTaskMapper).update(blocked);
		verify(generationConfigMapper).insert(any(AllocationTaskGenerationConfig.class));
	}

	private AllocationTaskGenerationConfigRequest config(String allowedPeriods) {
		return new AllocationTaskGenerationConfigRequest(
			null, null, allowedPeriods, null, null, null, null, null, null,
			null, null, null, null, null, null, null, null, null, null, null,
			null, null, null
		);
	}

	private void stubTaskInsert() {
		when(allocationTaskMapper.insert(any(AllocationTask.class))).thenAnswer(invocation -> {
			invocation.<AllocationTask>getArgument(0).setId(7L);
			return 1;
		});
	}
}
