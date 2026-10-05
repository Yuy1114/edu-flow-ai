# 教师画像JSONL快照接入说明

> ⚠️ **V3 状态 (2026-06-02)**: V3 pipeline 当前不消费教师画像快照。本文档保留作未来 V3 画像接入时的实现参考。详见 [17-V3-CP-SAT排课架构设计](../architecture/17-V3-CP-SAT排课架构设计.md)。
>

排课任务需要可复现输入。

如果 Python 每次直接读取最新教师画像，会出现：
- 教师生成方案后修改画像，旧方案难以解释。
- 同一个 `task_id` 重跑时输入悄悄变化。
- 方案质量问题无法追溯当时使用的画像内容。

因此当前链路是：

```text
Java 在任务开始前导出 JSONL
  ↓
请求 ML API 时传入 JSONL 绝对路径
  ↓
Python 只读取这份快照参与排课
```

---

## 服务端导出

入口：

```text
TeacherProfileSnapshotService.exportForAllocationTask(taskId)
```

查询方法：

```text
TeacherProfileMapper.findByAllocationTaskId(taskId)
```

SQL 逻辑：

```text
allocation_task_teaching_task
  → teaching_task.primary_teacher_id
  → teacher_profile.teacher_id
```

导出目录：

```text
ml/data/profiles/snapshots/
```

文件名：

```text
task_{taskId}_{yyyyMMddHHmmssSSS}.teacher_profiles.jsonl
```

---

## JSONL 行格式

每行一个教师：

```json
{
  "teacher_id": 12,
  "version": "v1",
  "parser_version": "teacher_profile_service_v1",
  "updated_at": "2026-05-25T12:30:00",
  "raw_text": "周一第一节尽量不要排，希望集中一点。",
  "availability_matrix_json": "[[0,0,0,0,0,0,0],[-1,0,0,0,0,0,0]]",
  "profile": {
    "avoidFirstPeriod": true,
    "preferCompactSchedule": true,
    "preferredMaxWeeklyHours": 12
  }
}
```

字段来源：

| JSONL 字段 | DB 字段 |
|------------|---------|
| teacher_id | `teacher_profile.teacher_id` |
| raw_text | `profile_note` |
| availability_matrix_json | `availability_matrix_json` |
| profile | `profile_preference_json` |
| updated_at | `updated_at` |

---

## 请求传递

`AllocationMlSchemeService.runModelScript` 会把快照路径放入请求体：

```json
{
  "task_id": 14,
  "teacher_profiles_jsonl": "/Users/.../ml/data/profiles/snapshots/task_14_20260525123000123.teacher_profiles.jsonl"
}
```

Python API schema：

```python
class GenerateRequest(BaseModel):
    task_id: int
    teacher_profiles_jsonl: str | None = None
```

然后调用：

```python
run(req.task_id, teacher_profiles_jsonl=req.teacher_profiles_jsonl)
```

---

## Python 归一化

入口：

```text
ml/scheduling/teacher_profiles.py
```

主要函数：

| 函数 | 作用 |
|------|------|
| `load_teacher_profiles_jsonl(path)` | 读取 JSONL，按 `teacher_id` 返回画像字典 |
| `normalize_profile(raw)` | 兼容不同画像 schema，清洗字段 |
| `hard_unavailable_slots(profile)` | 返回硬不可排 slot 集合 |
| `profile_penalty(profile, slot_id, ...)` | 计算软偏好 penalty 和解释 |

当前兼容字段：

| 输入字段 | 归一化结果 |
|----------|------------|
| `availability_matrix_json` 中的 `-1` | `hard_unavailable` |
| `hard_unavailable` / `hardUnavailable` | `hard_unavailable` |
| `soft_avoid` / `softAvoid` / `avoidSlots` | `soft_avoid` |
| `avoidFirstPeriod` | `avoid_periods=[1]` |
| `avoidLastPeriod` | `avoid_periods=[5]` |
| `preferredWeekdays` | `preferred_weekdays` |
| `preferCompactSchedule` | `prefer_compact_schedule` |
| `preferredMaxWeeklyHours` | `max_weekly_lessons` |

非法值处理：
- weekday 只保留 1~7。
- period 只保留 1~5。
- penalty clamp 到 0~100。
- 无法解析的单行 JSONL 会跳过。

---

## 在排课中如何生效

### 硬不可排

`pipeline.py` 构建 `AllocationTask` 时，会根据教师画像过滤候选 slot：

```text
candidate_slot_ids = global_slot_ids - profile.hard_unavailable
```

如果过滤后没有候选 slot，该教学任务无法生成合法方案。

### 软偏好

`ga.py` 在候选评分和 fitness 中计算画像 penalty：

```text
teacher_profile_penalty = profile_penalty(...)
```

常见 penalty：

| 规则 | 说明 |
|------|------|
| soft_avoid | 命中教师软避让时间 |
| avoid_period | 命中教师不喜欢的节次 |
| preferred_weekday_miss | 没排在教师偏好星期 |
| max_weekly_lessons | 超过教师偏好周课次 |
| compact_schedule | 教师希望集中，但当前任务过于分散 |

### 输出解释

`pipeline.py::_to_rows` 输出：

```json
{
  "teacher_profile_penalty": 60,
  "teacher_profile_penalty_explanation": "周一第一节尽量不排",
  "teacher_profile_penalty_breakdown": [
    {"rule": "soft_avoid", "penalty": 60, "reason": "周一第一节尽量不排"}
  ]
}
```

---

## 测试覆盖

相关测试位于：

```text
ml/tests/test_scheduling_core.py
```

已覆盖：
- JSONL 中 `period="*"` 归一化为 1~5。
- `availability_matrix_json` 中 `-1` 转为硬不可排。
- `avoidFirstPeriod` / `avoidLastPeriod` 转为避让节次。
- 教师 hard unavailable 会过滤候选 slot。
- 输出 rows 包含画像 penalty 和解释。

运行：

```bash
python3 -m unittest ml.tests.test_scheduling_core
```

---

## 后续建议

1. 把 LLM 输出 schema 从旧字段逐步收敛到 `hard_unavailable/soft_avoid/preferred_*`。
2. 给 JSONL 快照加 `task_id` 和 `snapshot_id`，方便前端展示和追溯。
3. 将 `teacher_profile_penalty_breakdown` 在前端方案详情中展示。
4. 将画像字段接入 LightGBM 训练样本和推理特征。
