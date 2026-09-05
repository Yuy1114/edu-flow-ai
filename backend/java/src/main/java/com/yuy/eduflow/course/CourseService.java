package com.yuy.eduflow.course;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import com.yuy.eduflow.timeslot.TeachingSessionTimePolicy;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.yuy.eduflow.enums.ActiveStatus;
import org.springframework.util.StringUtils;

@Service
public class CourseService {
	

	private final CourseMapper courseMapper;
	private final FormalScheduleMutationGuard formalScheduleMutationGuard;

	public CourseService(CourseMapper courseMapper, FormalScheduleMutationGuard formalScheduleMutationGuard) {
		this.courseMapper = courseMapper;
		this.formalScheduleMutationGuard = formalScheduleMutationGuard;
	}

	public List<Course> findAll(String keyword, String status) {
		return courseMapper.findAll(keyword, status);
	}

	public Map<String, Object> findAllPaged(String keyword, String status, int page, int size) {
		int offset = page * size;
		List<Course> content = courseMapper.findAllPaged(keyword, status, size, offset);
		long total = courseMapper.countAll(keyword, status);
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("content", content);
		result.put("total", total);
		result.put("page", page);
		result.put("size", size);
		return result;
	}

	public Course findById(Long id) {
		Course course = courseMapper.findById(id);
		if (course == null) {
			throw new ResourceNotFoundException("课程不存在");
		}
		return course;
	}

	public Course create(CourseRequest request) {
		Course course = toCourse(new Course(), request);
		courseMapper.insert(course);
		return findById(course.getId());
	}

	@Transactional
	public Course update(Long id, CourseRequest request) {
		Course existing = findById(id);
		formalScheduleMutationGuard.lockAndRejectCourse(id);
		Course course = toCourse(existing, request);
		courseMapper.update(course);
		return findById(id);
	}

	@Transactional
	public void delete(Long id) {
		findById(id);
		formalScheduleMutationGuard.lockAndRejectCourse(id);
		courseMapper.deactivate(id, ActiveStatus.INACTIVE.code());
	}

	private Course toCourse(Course course, CourseRequest request) {
		if (!StringUtils.hasText(request.name())) {
			throw new ValidationException("课程名称不能为空");
		}
		if (request.requiredHours() != null && request.requiredHours() <= 0) {
			throw new ValidationException("课程课时必须大于0");
		}
		String courseType = clean(request.courseType());
		if (TeachingSessionTimePolicy.periodCount(courseType) == 0) {
			throw new ValidationException("课程类型必须是理论课、上机课、实验课或实践课");
		}
		course.setName(request.name().trim());
		course.setCourseType(courseType);
		course.setRequiredRoomType(clean(request.requiredRoomType()));
		course.setRequiredHours(request.requiredHours());
		course.setDescription(clean(request.description()));
		course.setStatus(StringUtils.hasText(request.status()) ? ActiveStatus.from(request.status().trim()) : ActiveStatus.ACTIVE);
		return course;
	}

	private String clean(String value) {
		return StringUtils.hasText(value) ? value.trim() : null;
	}
}
