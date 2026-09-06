package com.yuy.eduflow.timeslot;

import com.yuy.eduflow.common.exception.ResourceNotFoundException;
import com.yuy.eduflow.common.exception.ValidationException;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
public class TimeSlotService {
	private final TimeSlotMapper timeSlotMapper;

	public TimeSlotService(TimeSlotMapper timeSlotMapper) {
		this.timeSlotMapper = timeSlotMapper;
	}

	public List<TimeSlot> findAll(Integer weekNumber, Integer dayOfWeek) {
		return timeSlotMapper.findAll(weekNumber, dayOfWeek);
	}

	public TimeSlot findById(Long id) {
		TimeSlot timeSlot = timeSlotMapper.findById(id);
		if (timeSlot == null) {
			throw new ResourceNotFoundException("时间段不存在");
		}
		return timeSlot;
	}

	public TimeSlot create(TimeSlotRequest request) {
		throw canonicalCatalogIsReadOnly();
	}

	public TimeSlot update(Long id, TimeSlotRequest request) {
		throw canonicalCatalogIsReadOnly();
	}

	public void delete(Long id) {
		throw canonicalCatalogIsReadOnly();
	}

	private ValidationException canonicalCatalogIsReadOnly() {
		return new ValidationException(
			"标准时间槽目录固定为18周×7天×11个45分钟原子节（4+4+3），运行期只读；请通过数据库迁移维护"
		);
	}

	private TimeSlot toTimeSlot(TimeSlot timeSlot, TimeSlotRequest request) {
		if (request.weekNumber() == null) {
			throw new ValidationException("周次不能为空");
		}
		if (request.weekNumber() < SchedulingTimePolicy.FIRST_WEEK) {
			throw new ValidationException("周次必须大于0");
		}
		if (request.weekNumber() > SchedulingTimePolicy.LAST_WEEK) {
			throw new ValidationException("周次必须在1到18之间");
		}
		if (request.dayOfWeek() == null) {
			throw new ValidationException("星期不能为空");
		}
		if (request.dayOfWeek() < 1 || request.dayOfWeek() > 7) {
			throw new ValidationException("星期必须在1到7之间");
		}
		if (request.periodIndex() == null) {
			throw new ValidationException("节次不能为空");
		}
		if (request.periodIndex() < SchedulingTimePolicy.FIRST_PERIOD) {
			throw new ValidationException("节次必须大于0");
		}
		if (request.periodIndex() > SchedulingTimePolicy.LAST_PERIOD) {
			throw new ValidationException("节次必须在1到10之间");
		}
		if (!StringUtils.hasText(request.label())) {
			throw new ValidationException("时间段标签不能为空");
		}
		timeSlot.setWeekNumber(request.weekNumber());
		timeSlot.setDayOfWeek(request.dayOfWeek());
		timeSlot.setPeriodIndex(request.periodIndex());
		timeSlot.setLabel(request.label().trim());
		return timeSlot;
	}
}
