package com.yuy.eduflow.allocation;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.conflict.ConflictCheckResultMapper;
import com.yuy.eduflow.enums.SchemeStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AllocationSchemeServiceLifecycleTest {
	@Mock AllocationSchemeMapper mapper;
	@Mock ConflictCheckResultMapper conflictMapper;
	@Mock AllocationTemplateDraftService draftService;
	private AllocationSchemeService service;

	@BeforeEach
	void setUp() {
		service = new AllocationSchemeService(mapper, conflictMapper, draftService);
	}

	@Test
	void genericUpdateCannotRewriteV35ServerOwnedSummaryOrLifecycle() {
		AllocationScheme scheme = scheme(SchemeStatus.CANDIDATE, "v3.5-dynamic-week");
		when(mapper.findByIdForUpdate(7L)).thenReturn(scheme);
		when(draftService.isV35(scheme)).thenReturn(true);
		AllocationSchemeRequest malicious = new AllocationSchemeRequest(
			999L, "篡改", "{\"generation_run_id\":\"other\"}", null, true, "CONFIRMED"
		);

		assertThrows(ValidationException.class, () -> service.update(7L, malicious));

		verify(mapper, never()).updateCandidateName(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
		verify(mapper, never()).update(org.mockito.ArgumentMatchers.any());
	}

	@Test
	void confirmedSchemeIsImmutableEvenThroughDelete() {
		AllocationScheme scheme = scheme(SchemeStatus.CONFIRMED, "legacy");
		when(mapper.findByIdForUpdate(7L)).thenReturn(scheme);

		assertThrows(ValidationException.class, () -> service.delete(7L));

		verify(mapper, never()).updateStatusIfCurrent(
			org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any()
		);
	}

	@Test
	void legacySchemeCreationEndpointIsClosed() {
		AllocationSchemeRequest request = new AllocationSchemeRequest(8L, "伪造方案", null, null, true, "CONFIRMED");

		assertThrows(ValidationException.class, () -> service.create(request));

		verify(mapper, never()).insert(org.mockito.ArgumentMatchers.any());
	}

	private AllocationScheme scheme(SchemeStatus status, String version) {
		AllocationScheme scheme = new AllocationScheme();
		scheme.setId(7L);
		scheme.setTaskId(8L);
		scheme.setStatus(status);
		scheme.setModelVersion(version);
		return scheme;
	}
}
