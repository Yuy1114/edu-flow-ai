package com.yuy.eduflow.ml;

import com.yuy.eduflow.common.ApiResponse;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ml/simulation")
public class SimulationController {

	private final MlApiClient mlApiClient;

	public SimulationController(MlApiClient mlApiClient) {
		this.mlApiClient = mlApiClient;
	}

	@PostMapping("/run")
	public ApiResponse<Map<String, Object>> run(@RequestBody Map<String, Object> request) {
		return ApiResponse.success(mlApiClient.runSimulation(request, false));
	}

	@PostMapping("/preview")
	public ApiResponse<Map<String, Object>> preview(@RequestBody Map<String, Object> request) {
		return ApiResponse.success(mlApiClient.previewSimulation(request));
	}

	@PostMapping("/timetable")
	public ApiResponse<Map<String, Object>> timetable(@RequestBody Map<String, Object> request) {
		return ApiResponse.success(mlApiClient.querySimulationTimetable(request));
	}

	@PostMapping("/boundary")
	public ApiResponse<Map<String, Object>> boundary(@RequestBody Map<String, Object> request) {
		return ApiResponse.success(mlApiClient.runSimulation(request, true));
	}
}
