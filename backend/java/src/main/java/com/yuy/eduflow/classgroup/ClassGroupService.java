package com.yuy.eduflow.classgroup;

import com.yuy.eduflow.assignment.FormalScheduleMutationGuard;
import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class ClassGroupService {
	private final ClassGroupMapper classGroupMapper;
	private final FormalScheduleMutationGuard formalScheduleMutationGuard;

	public ClassGroupService(ClassGroupMapper classGroupMapper, FormalScheduleMutationGuard formalScheduleMutationGuard) {
		this.classGroupMapper = classGroupMapper;
		this.formalScheduleMutationGuard = formalScheduleMutationGuard;
	}

	public List<ClassGroup> findAll(String keyword) {
		return classGroupMapper.findAll(keyword);
	}

	public Map<String, Object> findAllPaged(String keyword, int page, int size) {
		int offset = page * size;
		List<ClassGroup> content = classGroupMapper.findAllPaged(keyword, size, offset);
		long total = classGroupMapper.countAll(keyword);
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("content", content);
		result.put("total", total);
		result.put("page", page);
		result.put("size", size);
		return result;
	}

	public ClassGroup findById(Long id) {
		ClassGroup classGroup = classGroupMapper.findById(id);
		if (classGroup == null) {
			throw new ResourceNotFoundException("班级不存在");
		}
		return classGroup;
	}

	public ClassGroup create(ClassGroupRequest request) {
		ClassGroup classGroup = toClassGroup(new ClassGroup(), request, null);
		classGroupMapper.insert(classGroup);
		return findById(classGroup.getId());
	}

	@Transactional
	public ClassGroup update(Long id, ClassGroupRequest request) {
		findById(id);
		formalScheduleMutationGuard.lockAndRejectClassGroup(id);
		ClassGroup classGroup = toClassGroup(new ClassGroup(), request, id);
		classGroup.setId(id);
		classGroupMapper.update(classGroup);
		return findById(id);
	}

	@Transactional
	public void delete(Long id) {
		findById(id);
		formalScheduleMutationGuard.lockAndRejectClassGroup(id);
		if (classGroupMapper.countTeachingTaskRefs(id) > 0) {
			throw new ValidationException("班级已被教学任务引用，不能删除");
		}
		classGroupMapper.delete(id);
	}

	private ClassGroup toClassGroup(ClassGroup classGroup, ClassGroupRequest request, Long excludeId) {
		if (!StringUtils.hasText(request.name())) {
			throw new ValidationException("班级名称不能为空");
		}
		String name = request.name().trim();
		if (classGroupMapper.countByName(name, excludeId) > 0) {
			throw new ValidationException("班级名称已存在");
		}
		if (request.studentCount() == null || request.studentCount() <= 0) {
			throw new ValidationException("班级人数必须大于0");
		}
		classGroup.setName(name);
		classGroup.setMajor(clean(request.major()));
		classGroup.setDepartment(clean(request.department()));
		classGroup.setGrade(clean(request.grade()));
		classGroup.setStudentCount(request.studentCount());
		return classGroup;
	}

	private String clean(String value) {
		return StringUtils.hasText(value) ? value.trim() : null;
	}
}
