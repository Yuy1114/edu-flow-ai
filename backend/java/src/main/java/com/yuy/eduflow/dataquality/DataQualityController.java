package com.yuy.eduflow.dataquality;

import com.yuy.eduflow.common.ApiResponse;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ml/dataset")
public class DataQualityController {

	private final DataQualityService dataQualityService;

	public DataQualityController(DataQualityService dataQualityService) {
		this.dataQualityService = dataQualityService;
	}

	@GetMapping("/board")
	public ApiResponse<Map<String, Object>> board() {
		return ApiResponse.success(dataQualityService.board());
	}

	@GetMapping("/snapshots")
	public ApiResponse<List<DatasetQualitySnapshot>> snapshots() {
		return ApiResponse.success(dataQualityService.recentSnapshots());
	}

	@PostMapping("/snapshots")
	public ApiResponse<DatasetQualitySnapshot> capture(
		@RequestParam(required = false) String capturedBy
	) {
		return ApiResponse.success(dataQualityService.capture(capturedBy));
	}
}
