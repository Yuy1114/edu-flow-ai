# LightGBM 模型训练架构设计

> ⚠️ **V3 更新 (2026-06-02)**: 本文档描述的 LightGBM 作为"GA 局部评分器"的角色已被 V3 的 **Placement Model** (多分类) 取代。训练闭环方法论（冷启动→反馈重训→评估发布）仍然适用，但模型角色从 `score(task, slot, room) → [0,1]` 变为 `predict(task) → TopK resource_key`。详见 [17-V3-CP-SAT排课架构设计](./17-V3-CP-SAT排课架构设计.md)。
>

---

## 设计边界

LightGBM 是排课链路中的局部评分器，不替代硬约束。

```
score(task, template, slot, classroom) -> 0.0 ~ 1.0
```

它负责学习：
- 教务最终接受哪些候选
- 哪些时间 / 教室组合更容易被调整
- 教师画像中的软偏好
- 教室容量、类型、楼宇与课程之间的匹配偏好
- 历史冲突、驳回、调整行为中的负反馈

它不负责判断：
- 教师 / 班级 / 教室硬冲突
- 可用周 / 星期 / 节次硬过滤
- 教学任务是否完整排完
- 教师画像 hard_unavailable

硬约束仍由 GA / repair / pipeline 校验精确执行。

---

## 总体闭环

```
基础规则样本
       ↓
训练 base 模型
       ↓
排课生成多套候选方案
       ↓
教务选择 / 调整 / 确认 / 冲突检测
       ↓
导出反馈 JSON
       ↓
构造 feedback samples.csv
       ↓
训练候选反馈模型
       ↓
离线评估 + 发布门槛
       ↓
发布到 feedback/current
       ↓
下一次 GA 自动加载新模型
```

模型加载顺序：

```
ml/models/feedback/current/schedule_ranker.txt
  fallback → ml/models/base/schedule_ranker_v1.txt
  fallback → score = 0.0
```

---

## 模型目录

```text
ml/models/
├── base/
│   ├── schedule_ranker_v1.txt
│   └── feature_schema.json
└── feedback/
    ├── current/
    │   ├── schedule_ranker.txt
    │   └── feature_schema.json
    └── archive/
        └── 20260525143000/
            ├── schedule_ranker.txt
            └── feature_schema.json
```

说明：
- `base/` 是规则样本训练出的冷启动模型。
- `feedback/archive/{version}/` 保存每次训练产物，便于回滚和审计。
- `feedback/current/` 是线上推理使用的反馈模型。
- `feature_schema.json` 是训练 / 推理特征契约，必须和模型一起发布。

---

## 样本来源

### 1. 规则冷启动样本

脚本：

```text
ml/scripts/generate_training_samples.py
```

输入：
- active teaching_task
- classroom
- time_slot
- teacher_profile

输出：

```text
ml/data/base/samples.csv
```

用途：
- 没有教务反馈时提供初始模型。
- 学习容量、教室类型、早晚课、基础冲突等规则信号。

局限：
- 标签来自规则打分，不是真实偏好。
- 只能用于冷启动，不应长期作为唯一训练数据。

### 2. 教务反馈样本

导出入口：

```text
server MlFeedbackTrainingService.exportFeedback(taskId)
```

导出内容：
- allocation_scheme
- allocation_item
- allocation_scheme_feedback
- allocation_item_adjustment_log
- conflict_check_result

样本构造脚本：

```text
ml/scripts/build_feedback_training_samples.py
```

输入：

```text
ml/data/feedback/exports/feedback_task_{taskId}_{time}.json
```

输出：

```text
ml/data/feedback/samples/feedback_samples_task_{taskId}_{time}.csv
```

---

## 标签策略

反馈样本使用二分类式回归标签，LightGBM 仍输出 0~1 分数。

| 来源 | label | sample_weight | 说明 |
|------|------:|--------------:|------|
| confirmed / selected 方案项 | 1.0 | 1.0 | 教务接受的候选 |
| adjustment after | 1.0 | 1.4 | 教务调整后的目标位置 |
| adjustment before | 0.0 | 1.2 | 被教务移走的位置 |
| unresolved conflict item | 0.0 | 1.3 | 冲突或无效项 |
| rejected item / scheme | 0.0 | 1.5 | 明确负反馈，后续补充 |

训练时使用 `sample_weight`，让强反馈比普通确认更有影响。

---

## 特征契约

特征由 `feature_schema.json` 固化，训练和推理必须一致。

### 任务特征

```text
course_type
total_hours
required_room_type
class_group_count
total_student_count
teacher_department
teacher_title
teacher_max_weekly_hours
required_fragments
```

### 教室特征

```text
room_capacity
room_type
room_building
capacity_margin
capacity_ratio
is_capacity_enough
is_room_type_match
```

### 时间特征

```text
week_number
day_of_week
period_index
is_morning
is_afternoon
is_evening
is_weekend
is_early_period
is_late_period
```

### 方案状态特征

```text
teacher_occupied_at_slot
class_occupied_at_slot
room_occupied_at_slot
teacher_day_load
class_day_load
teacher_week_load
class_week_load
scheme_day_load
room_day_load
room_week_load
task_day_load
has_teacher_conflict
has_class_conflict
has_room_conflict
has_hard_conflict
```

### 教师画像特征

来自 `docs/architecture/02-教师画像作用路径设计.md`：

```text
teacher_matrix_value
teacher_preferred_weekday_match
teacher_avoid_slot_match
teacher_avoid_first_period
teacher_avoid_last_period
teacher_prefer_compact_schedule
teacher_preferred_max_weekly_hours
```

画像 hard_unavailable 不作为模型自由学习对象，它应该在候选阶段硬过滤。

---

## 训练流程

### 冷启动训练

```text
generate_training_samples.py
       ↓
train_lightgbm.py --data ml/data/base/samples.csv
       ↓
ml/models/base/schedule_ranker_v1.txt
ml/models/base/feature_schema.json
```

冷启动模型可手动执行，也可在初始化环境时执行。

### 反馈重训

```text
exportFeedback(taskId 或 all)
       ↓
build_feedback_training_samples.py
       ↓
train_lightgbm.py --data feedback_samples.csv --model archive/{version}/schedule_ranker.txt --schema archive/{version}/feature_schema.json
       ↓
评估 candidate model
       ↓
通过门槛则发布到 feedback/current
```

当前 Java 服务 `MlFeedbackTrainingService.train(taskId)` 已覆盖：
- 读取最新反馈导出
- 构造 CSV 样本
- 调用训练脚本
- 写入 `model_training_log`
- 归档模型
- 发布 current 模型

后续需要补强的是发布门槛和对比评估。

---

## 评估与发布门槛

训练输出指标：

```text
mae
rmse
r2
auc
score_separation
score_std
pos_mean
neg_mean
feature_importance_top20
```

建议发布条件：

| 条件 | 建议阈值 |
|------|----------|
| sample_count | >= 100 |
| positive_count | >= 20 |
| negative_count | >= 20 |
| auc | >= 0.65 |
| score_separation | >= 0.05 |
| score_std | >= 0.03 |
| schema compatible | true |

如果未通过：
- 训练产物保留在 archive。
- `model_training_log.status` 标记为 FAILED 或 NEED_REVIEW。
- 不覆盖 `feedback/current`。

如果通过：
- 复制 archive 模型到 `feedback/current`。
- 更新 `model_training_log.status=SUCCEEDED`。
- 下一次 GA 自动加载新模型。

---

## 灰度与回滚

### 灰度策略

第一阶段建议手动发布：
- 管理员点击训练
- 系统展示指标
- 指标通过后发布 current

第二阶段可自动发布：
- 每周固定重训
- 或累计 N 条反馈后触发

### 回滚策略

回滚只需要替换：

```text
ml/models/feedback/current/schedule_ranker.txt
ml/models/feedback/current/feature_schema.json
```

可从 `feedback/archive/{version}/` 恢复，也可以删除 `feedback/current` 回退到 `base` 模型。

---

## 与排课生成的关系

生成阶段不关心训练细节，只依赖当前可用模型：

```
AssignmentScorer
  → 读取 MODEL_PATH / FEATURE_SCHEMA_PATH
  → score(task, template, slot, classroom)
  → 返回 0.0~1.0
```

使用位置：
- 初始化 top-k 采样
- repair 候选排序
- fitness 软质量项
- 输出 row 的 predicted_score

如果模型不可用：
- 记录日志
- `score = 0.0`
- GA 仍可使用规则继续生成方案

当前运行时诊断会写入 `ga_summary.json`：

```json
{
  "lightgbm": {
    "enabled": true,
    "model_path": "ml/models/base/schedule_ranker_v1.txt",
    "feature_schema_path": "ml/models/base/feature_schema.json",
    "feature_count": 47,
    "categorical_feature_count": 6,
    "cache_size": 1234,
    "disabled_reason": ""
  }
}
```

加载优先级：

```text
ml/models/feedback/current/schedule_ranker.txt
  fallback → ml/models/base/schedule_ranker_v1.txt
  fallback → disabled_reason + score=0.0
```

---

## 数据质量风险

| 风险 | 影响 | 策略 |
|------|------|------|
| 只有正样本 | 模型全部预测高分 | 阻止发布 |
| 只有负样本 | 模型全部预测低分 | 阻止发布 |
| 样本太少 | 指标不稳定 | 阻止发布或 NEED_REVIEW |
| 反馈偏向单一任务 | 泛化差 | 支持 taskId/all 两种训练范围 |
| 教师画像解析错误 | 学到错误偏好 | hard 由规则校验，soft 保留解释 |
| schema 不一致 | 推理失败或质量异常 | schema 与模型一起发布 |
| score 饱和 | top-k 排序失效 | 检查 score_std |

---

## 后续实现顺序

1. 补齐发布门槛：样本数、正负样本、AUC、score_separation、score_std。
2. 训练失败时保留 archive，但不发布 current。
3. 训练完成后生成对比报告：previous vs candidate。
4. 前端展示训练报告、当前模型路径、发布状态和回滚入口。
5. 前端展示训练日志、指标、发布状态和回滚入口。
6. 增加定期训练或“累计反馈数达到阈值”提醒。
