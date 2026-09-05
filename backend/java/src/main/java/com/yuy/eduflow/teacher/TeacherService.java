package com.yuy.eduflow.teacher;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ConflictException;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.yuy.eduflow.enums.ActiveStatus;
import org.springframework.util.StringUtils;

@Service
public class TeacherService {
	
	private static final String DEFAULT_ROLE = "TEACHER";

	private final TeacherMapper teacherMapper;
	private final FormalScheduleMutationGuard formalScheduleMutationGuard;

	public TeacherService(TeacherMapper teacherMapper, FormalScheduleMutationGuard formalScheduleMutationGuard) {
		this.teacherMapper = teacherMapper;
		this.formalScheduleMutationGuard = formalScheduleMutationGuard;
	}

	public List<Teacher> findAll(String keyword, String status) {
		return teacherMapper.findAll(keyword, status);
	}

	public Map<String, Object> findAllPaged(String keyword, String status, int page, int size) {
		int offset = page * size;
		List<Teacher> content = teacherMapper.findAllPaged(keyword, status, size, offset);
		long total = teacherMapper.countAll(keyword, status);
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("content", content);
		result.put("total", total);
		result.put("page", page);
		result.put("size", size);
		return result;
	}

	public Teacher findById(Long id) {
		Teacher teacher = teacherMapper.findById(id);
		if (teacher == null) {
			throw new ResourceNotFoundException("教师不存在");
		}
		return teacher;
	}

	public Teacher create(TeacherRequest request) {
		Teacher teacher = toTeacher(new Teacher(), request, true);
		ensureEmployeeNoAvailable(teacher.getEmployeeNo(), null);
		teacherMapper.insert(teacher);
		return findById(teacher.getId());
	}

	@Transactional
	public Teacher update(Long id, TeacherRequest request) {
		Teacher existing = findById(id);
		formalScheduleMutationGuard.lockAndRejectTeacher(id);
		Teacher teacher = toTeacher(existing, request, false);
		ensureEmployeeNoAvailable(teacher.getEmployeeNo(), id);
		teacherMapper.update(teacher);
		return findById(id);
	}

	@Transactional
	public void delete(Long id) {
		findById(id);
		formalScheduleMutationGuard.lockAndRejectTeacher(id);
		teacherMapper.deactivate(id, ActiveStatus.INACTIVE.code());
	}

	private Teacher toTeacher(Teacher teacher, TeacherRequest request, boolean requirePassword) {
		if (request == null) {
			throw new ValidationException("请求不能为空");
		}
		if (!StringUtils.hasText(request.employeeNo())) {
			throw new ValidationException("工号不能为空");
		}
		if (requirePassword && !StringUtils.hasText(request.password())) {
			throw new ValidationException("密码不能为空");
		}
		if (!StringUtils.hasText(request.name())) {
			throw new ValidationException("教师姓名不能为空");
		}
		if (!StringUtils.hasText(request.department())) {
			throw new ValidationException("所属部门不能为空");
		}
		teacher.setEmployeeNo(request.employeeNo().trim());
		if (StringUtils.hasText(request.password())) {
			teacher.setPassword(request.password().trim());
		}
		if (!StringUtils.hasText(teacher.getPassword())) {
			throw new ValidationException("密码不能为空");
		}
		teacher.setRole(StringUtils.hasText(request.role()) ? request.role().trim() : defaultRole(teacher.getRole()));
		teacher.setName(request.name().trim());
		teacher.setDepartment(request.department().trim());
		teacher.setTitle(StringUtils.hasText(request.title()) ? request.title().trim() : null);
		teacher.setStatus(StringUtils.hasText(request.status()) ? ActiveStatus.from(request.status().trim()) : ActiveStatus.ACTIVE);
		return teacher;
	}

	private void ensureEmployeeNoAvailable(String employeeNo, Long currentTeacherId) {
		Teacher existing = teacherMapper.findByEmployeeNo(employeeNo);
		if (existing != null && !Objects.equals(existing.getId(), currentTeacherId)) {
			throw new ConflictException("工号已存在");
		}
	}

	private String defaultRole(String currentRole) {
		return StringUtils.hasText(currentRole) ? currentRole : DEFAULT_ROLE;
	}
}
