# CatBoost + 两阶段拆分：模型改进方案

> 更新时间：2026-06-08
> 状态：规划中

## 问题背景

当前 LightGBM Placement Model 的多样性不足：

| 指标 | 当前值 |
|------|--------|
| 类别数 | 1743 种 (教室, 天, 节次) |
| 训练样本 | 4390 条 |
| 每类平均样本 | 2.5 条 |
| 模型推荐组合数 | 143 种（仅占 8%） |
| 核心原因 | 样本极度不均衡 + hash 编码丢失语义 |

## 方案：CatBoost + 两阶段拆分

```
阶段 1: 预测 (天, 节次)     → 35 类，每类 ~125 条
阶段 2: 对每个时段预测教室   → 平均每子模型 ~50 类，每类 ~10 条
```

CatBoost 原生支持类别特征（`teacher_name`, `course_code`），不再依赖 hash 编码。

## 实施步骤

### Step 1: 安装 CatBoost

```bash
source backend/python/.venv/bin/activate
python3 -m pip install catboost
```

### Step 2: 写训练脚本 — `backend/python/scripts/train_catboost_two_stage.py`

整体流程：

```
加载 parsed/ 目录下的 JSONL 数据
  ↓
拼接特征：course_code, teacher_name, course_type, major, department, grade...
  ↓
阶段 1：CatBoost 分类器 → 预测 slot_label = "day|period"
  ├── 输入：教学任务特征
  ├── 输出：35 个时段类别
  └── 评估：hit@1 / hit@5
  ↓
阶段 2：对每个时段训一个子分类器 → 预测 room
  ├── 输入：教学任务特征 + 已确定的时段
  ├── 输出：该时段下可能的教室
  └── 评估：hit@1 / hit@5
  ↓
组合输出：TopK (day, period, room) 候选 → 一份新的 candidates.jsonl
```

**关键细节**：

- 特征列：`course_code`, `teacher_name`, `course_name`, `class_grade`, `class_major`, `class_department`, `course_type`, `required_room_type`, `total_hours`, `student_count`
- 类别特征（`cat_features`）：所有文本列
- `class_weights="Balanced"` 处理不均衡
- 阶段 2 每个子模型只在该时段的数据上训练，数据量小所以用浅树（`depth=4`, `iterations=100`）
- 对样本量 < 20 的冷门时段直接 fallback 到全量数据模型

### Step 3: 模型评估

运行 `check_model_diversity.py` 对比新旧模型：

| 指标 | 旧模型 (LightGBM) | 新模型 (CatBoost 两阶段) |
|------|-------------------|------------------------|
| 推荐组合数 | 143 | 预期大幅提升 |
| hit@1 | ? | ? |
| hit@10 | ? | ? |
| 时段 Gini | 0.2857 | 预期更低 |

### Step 4: 集成到排课链路

将训练好的 CatBoost 模型输出接入 `scheduling_service.py`：

```
训练脚本 → 产出模型文件 → placement_candidates.py 加载 → 输出 candidates.jsonl
                                                         ↓
                                                    task_plans → CP-SAT
```

需要改 `placement_direct.py` 加上 CatBoost 的推理接口。

### Step 5: 回归测试

跑一次完整排课验证：

```bash
curl -X POST http://localhost:8001/api/ml/v3/generate \
  -H "Content-Type: application/json" \
  -d '{"allocation_task_id":1,"generation_mode":"FEASIBILITY"}'
```

验证：
- CP-SAT 状态不为 INFEASIBLE
- 方案无硬冲突
- 任务覆盖率 100%

## 风险点

| 风险 | 应对 |
|------|------|
| 阶段 2 冷门时段子模型样本少 | 不足 20 条的时段 fallback 到全量模型 |
| 推理速度变慢（35+ 个子模型） | 每个子模型很浅（depth=4），总推理时间应在 1s 内 |
| CatBoost vs LightGBM 接口不一致 | 包装统一推理接口 `predict_topk(task, k)` |
| 两阶段串行错误传递 | 阶段 1 的 top-5 时段分别送阶段 2，合并候选 |
