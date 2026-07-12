# 教师画像进入 CP-SAT 接入点设计

> 来源：`docs/architecture/19-毕设最终系统架构设计.md`、`docs/architecture/18-V3-教师画像MVP设计.md`、当前 `ml/scheduling_v3` 代码。
> 本文档用于进入 Phase 3 前的代码梳理，明确教师画像满足度应接入哪一层、如何进入 CP-SAT objective、以及当前代码的真实缺口。

---

## 1. 当前结论

V3 当前排课链路是：

```text
pipeline.py
  → Placement Model 推理
  → placement_candidates.jsonl
  → plan_templates.py 生成 task_plans.jsonl
  → cp_sat_selector.py 选择全局无冲突方案
  → schemes.jsonl
```

教师画像进入 CP-SAT 的最佳切入点不是直接改 Java，也不是直接改最终 `schemes.jsonl`，而是在 Python V3 链路里增加：

```text
task plan 画像满足度计算
  → CpSatPlanOption 增加 teacher_profile_score / penalty
  → CP-SAT objective 使用 quality_score + profile_score
  → schemes.jsonl 输出画像解释
```

关键发现：梳理时发现 `cp_sat_selector.py` 没有显式 `model.Maximize(...)` objective。当前已补上 `quality_score` objective 基线，后续可以在此基础上接入教师画像分数。原先它主要依赖：

- 每个 task 选一个 plan 的硬约束。
- 教师、班级、教室同时间 AtMostOne 硬约束。
- 多方案差异约束。
- greedy hint 和 search strategy。
- `quality_score` 目前用于 greedy hint 排序和最终输出汇总，但没有被 CP-SAT 直接最大化。

因此 Phase 3 不只是“加一个画像权重”，还需要先补上显式 objective。

---

## 2. 关键代码位置

### 2.1 总管线

文件：`ml/scheduling_v3/pipeline.py`

关键函数：

```text
run_v3_pipeline(allocation_task_id, ...)
```

当前步骤：

```text
Step 1: 加载 DB 数据
Step 2: Placement Model inference
Step 3: Template generation
Step 4: CP-SAT global plan selection
```

CP-SAT 调用位置：

```python
cp_sat_summary = select_cp_sat_global_plans_jsonl(
    task_plans_path,
    time_slot_id_by_coord=time_slot_id_by_coord,
    scheme_count=resolved_scheme_count,
    time_limit_seconds=solver_time_limit_seconds,
    output_dir=out_dir,
)
```

### 2.2 Task Plan 生成

文件：`ml/scheduling_v3/plan_templates.py`

关键函数：

```text
generate_task_plans_jsonl(...)
_build_task_plan_row(...)
_build_plans(...)
_build_segments(...)
_plan_score(...)
```

当前 plan 结构：

```json
{
  "teaching_task_id": 123,
  "task": {...},
  "plans": [
    {
      "plan_id": "123_p001",
      "plan_rank": 1,
      "segments": [...],
      "score": 0.93,
      "valid": true
    }
  ]
}
```

画像接入建议：在 plan 上新增：

```json
{
  "teacher_profile_score": 0.86,
  "teacher_profile_penalty": 0.14,
  "teacher_profile_reasons": [
    "命中教师偏好星期",
    "避开第1节"
  ]
}
```

### 2.3 CP-SAT 方案选择

文件：`ml/scheduling_v3/cp_sat_selector.py`

关键数据结构：

```text
CpSatPlanOption
CpSatTaskPlans
```

当前 `CpSatPlanOption` 字段：

```text
task_index
plan_index
plan_id
teaching_task_id
teacher_id
class_group_ids
assignments
resource_keys
hard_static
quality_score
```

建议新增字段：

```text
teacher_profile_score: float
teacher_profile_penalty: float
teacher_profile_reasons: tuple[str, ...]
```

当前 `_solve_one_scheme()` 已有显式 `quality_score` objective 基线。

后续接入教师画像时，将 objective 从：

```python
model.Maximize(sum(quality_score_terms))
```

演进为：

```python
objective_terms = []
for task in tasks:
    for option in task.options:
        var = variables[(option.task_index, option.plan_index)]
        score = option.quality_score * model_weight
        score += option.teacher_profile_score * teacher_profile_weight
        score -= option.teacher_profile_penalty * teacher_profile_penalty_weight
        objective_terms.append(int(score * OBJECTIVE_SCALE) * var)
model.Maximize(sum(objective_terms))
```

---

## 3. 教师画像数据来源

当前后端 `/api/ml/teacher-profiles/v3` 已返回：

```text
final_profile
feedback_profile
feedback_evidence_summary
feedback_confidence
```

但 Python V3 pipeline 目前不直接调用 Java API。更稳的 MVP 做法是：

```text
Python 侧读取 data/profiles/v3/teacher_profiles_v3.json
```

短期方案：

- 使用历史画像 JSON 中的 `final_profile`。
- 如果后续要使用 Java 合并后的声明画像和反馈画像，需要增加一个 Java → Python 的画像快照导出步骤。
- 不建议 Python 在排课过程中直接调用 Java HTTP 接口，避免本地运行和部署耦合。

推荐落地路径：

```text
Java 侧 V3 画像接口
  → 导出 teacher_profiles_runtime.json
  → Python pipeline 读取该快照
  → task plan 计算画像满足度
```

MVP 也可以先在 Python 中只读取 `teacher_profiles_v3.json`，把声明/反馈画像接入放到下一步。

---

## 4. 画像满足度计算规则

第一版不要复杂，先覆盖已存在的可计算字段：

| 字段 | 规则 | 影响 |
|---|---|---|
| `avoid_early_period` | plan 中出现第 1 节则扣分 | 软惩罚 |
| `avoid_late_period` | plan 中出现第 5/6 节则扣分 | 软惩罚 |
| `preferred_weekdays` | 命中偏好星期加分，未命中扣分 | 软目标 |
| `preferred_periods` | 命中偏好节次加分，未命中扣分 | 软目标 |
| `max_daily_lessons` | 单日 session 超过上限扣分 | 软惩罚 |
| `declared_avoid_slots` | 命中声明避让时间扣分 | 软惩罚 |

输出建议：

```json
{
  "teacher_profile_score": 0.83,
  "teacher_profile_penalty": 0.17,
  "teacher_profile_reasons": [
    "第1节避让满足",
    "偏好星期命中 2/3"
  ],
  "teacher_profile_components": {
    "early_period": 1.0,
    "late_period": 1.0,
    "preferred_weekday": 0.67,
    "preferred_period": 0.8,
    "daily_load": 1.0
  }
}
```

---

## 5. Objective 设计

当前已采用线性加权：

```text
objective =
  model_weight * placement_quality_score
  + teacher_profile_weight * teacher_profile_score * session_count
  - teacher_profile_penalty_weight * teacher_profile_penalty * session_count
```

当前权重默认值：

```text
model_weight = 1.0
teacher_profile_weight = 0.15
teacher_profile_penalty_weight = 0.15
```

当前已接入任务生成配置：

```text
allocation_task_generation_config.model_weight
  → CP-SAT model objective weight

allocation_task_generation_config.teacher_profile_penalty_scale
  → 教师画像权重倍率
  → 100 = 默认 0.15
  → 0 = 关闭教师画像 objective 影响
  → 200 = 默认权重翻倍
```

硬约束仍然通过 CP-SAT constraint 保证，不进入软目标：

- 教师同时间冲突。
- 班级同时间冲突。
- 教室同时间冲突。
- 每个 teaching task 必须选一个 plan。

原因：第一版不让画像压过 Placement Model，只作为方案排序微调。

---

## 6. 输出解释

`schemes.jsonl` 当前 item 已包含：

```text
teaching_task_id
time_slot_id
classroom_id
week_number
day_of_week
period_index
teacher_id
class_group_ids
placement_score
selected_plan_id
template_id
```

建议在每个 item 或 scheme summary 中增加：

```text
teacher_profile_score
teacher_profile_penalty
teacher_profile_reasons
```

当前已挂在 item 上，并通过 Java `AllocationItem` / `AllocationItemView` 入库与返回，前端方案详情可展示画像分、画像扣分原因。

---

## 7. 推荐开发顺序

1. [x] 在 `plan_templates.py` 中加载教师画像快照。
2. [x] 在 `_build_plans()` / `_plan_score()` 附近计算 plan 级画像分数。
3. [x] 扩展 `task_plans.jsonl`，写入 `teacher_profile_score`、`teacher_profile_penalty`、`teacher_profile_reasons`。
4. [x] 扩展 `CpSatPlanOption`，读取 plan 级画像字段。
5. [x] 在 `_solve_one_scheme()` 中增加显式 `model.Maximize(...)`。
6. [x] 先用 `quality_score` 做 objective，确保行为不退化。
7. [x] 再加入教师画像权重。
8. [x] 在 `_scheme_to_json()` 中输出画像解释字段。
9. [ ] 跑一次 V3 pipeline，对比：冲突数、平均满足度、低满足教师数。

---

## 8. 风险与边界

### 风险 1：objective 基线需要防退化

当前已补 `quality_score` objective 基线。后续加入画像字段时，需要先确认仅使用 `quality_score` 的方案质量和冲突表现不退化，再逐步叠加教师画像权重。

### 风险 2：画像样本不足

反馈画像当前只展示证据，不覆盖 `final_profile`。Phase 3 第一版建议使用 `final_profile`，不要直接使用低置信度 `feedback_profile`。

### 风险 3：权重过高

画像权重过高会让方案过度迁就个别教师，牺牲整体课表结构。第一版权重必须小。

### 风险 4：Python 与 Java 画像不一致

Java 接口已经合并声明画像和反馈证据，但 Python 默认读本地 JSON。后续需要明确是否导出 Java runtime 画像快照给 Python 使用。

---

## 9. 本阶段完成标准

- `task_plans.jsonl` 中每个 plan 有教师画像分数。
- `cp_sat_selector.py` 有显式 objective。
- objective 包含 placement quality 与 teacher profile score。
- `schemes.jsonl` 输出画像解释。
- Java 入库后不破坏现有冲突检测。
- 前端满足度报告能看到接入前后变化。
