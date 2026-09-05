package com.yuy.eduflow.ml;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuy.eduflow.common.ApiResponse;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class SimulationControllerTest {

	@Mock
	private MlApiClient mlApiClient;

	private SimulationController controller;

	@BeforeEach
	void setUp() {
		controller = new SimulationController(mlApiClient);
	}

	@Test
	void previewProxiesTheCanonicalSimulationRequest() {
		Map<String, Object> request = Map.of("seed", 7, "courses", 24);
		Map<String, Object> payload = Map.of("simulation_id", "sim-test");
		when(mlApiClient.previewSimulation(request)).thenReturn(payload);

		ApiResponse<Map<String, Object>> response = controller.preview(request);

		assertEquals(0, response.code());
		assertSame(payload, response.data());
		verify(mlApiClient).previewSimulation(request);
	}

	@Test
	void runAndBoundaryUseDifferentPythonEndpoints() {
		Map<String, Object> request = Map.of("simulation_id", "sim-test");
		Map<String, Object> payload = Map.of("status", "ok");
		when(mlApiClient.runSimulation(request, false)).thenReturn(payload);
		when(mlApiClient.runSimulation(request, true)).thenReturn(payload);

		assertSame(payload, controller.run(request).data());
		assertSame(payload, controller.boundary(request).data());
		verify(mlApiClient).runSimulation(request, false);
		verify(mlApiClient).runSimulation(request, true);
	}

	@Test
	void timetableProxiesFilterRequest() {
		Map<String, Object> request = Map.of("simulation_id", "sim-test", "teacher", "张老师 1");
		Map<String, Object> payload = Map.of("total", 2);
		when(mlApiClient.querySimulationTimetable(request)).thenReturn(payload);

		assertSame(payload, controller.timetable(request).data());
		verify(mlApiClient).querySimulationTimetable(request);
	}
}
