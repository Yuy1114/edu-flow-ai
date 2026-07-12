# V3 — 基于 Placement Model + CP-SAT 全局方案选择的智能排课架构

> 状态：✅ 当前生产架构  
> 更新时间：2026-06-02  
> 取代：[15-候选池 GA 架构](./15-基于候选空间压缩与学习评分引导的智能排课架构.md)、[16-Beam Search 简化方案](./16-实时排课简化方案.md)

---

## 一句话定义

> **LightGBM 多分类模型为每个教学任务预测 TopK (教室, 星期, 节次) 候选，模板生成器为每个任务构造多种周次分布方案，CP-SAT 求解器在全局无冲突约束下为所有任务同时选择最优方案组合。**

---

## 架构全景

```
┌─────────────────────────────────────┐
│          allocation_task_id         │
│     (Java 只传 ID，不展开数据)       │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Step 1: 数据加载 (DB → 内存)        │
│  · teaching_tasks (2615, 已清洗)     │
│  · classrooms (330), time_slots     │
│  · courses (673), class_groups      │
│  · teachers (624)                   │
│  · generation_config                │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Step 2: Placement Model 推理       │
│  · LightGBM 多分类 (3953 类)        │
│  · 13 特征 → TopK resource_key      │
│  · 8 线程并行，~2s (2615 tasks)      │
│  · 输出: placement_candidates.jsonl │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Step 3: 模板生成 (Task Plans)       │
│  · 每个 task 构造多种周次分布方案    │
│  · WeekUsageAllocator 学期均匀分布  │
│  · 每 task 最多 120 plans           │
│  · 8 线程并行，~4s                   │
│  · 输出: task_plans.jsonl           │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Step 4: CP-SAT 全局方案选择         │
│  · OR-Tools CP-SAT solver          │
│  · 每个 task 选一个 plan             │
│  · 硬约束: 教师/班级/教室不冲突       │
│  · 软目标: 最大化 quality_score      │
│  · 多方案: scheme_count 个独立求解   │
│  · 输出: schemes.jsonl + summary    │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Java 入库 → 冲突检测 → 前端展示     │
└─────────────────────────────────────┘
```

---

## 模块详解

### Step 1: 数据加载

**入口**: `pipeline.run_v3_pipeline(allocation_task_id)`

从 MySQL 加载排课所需的全部数据：
- 教学任务列表（通过 `allocation_task_teaching_task` 关联）
- 教室、课程、班级、教师、时间段
- 生成配置 (`generation_config`)

数据已事先清洗：
| 表 | 清洗前 | 清洗后 |
|----|--------|--------|
| classrooms | 408 | 330 |
| courses | 704 | 673 |
| teaching_tasks | 2957 | 2615 |
| timetables | 87536 | 45475 |

剔除项：实践课(342)、脏数据教室、名称不匹配记录。

**代码位置**: `ml/scheduling_v3/pipeline.py` Lines 74-127

### Step 2: Placement Model

**模型类型**: LightGBM 多分类 (multiclass)  
**类别数**: 3953 (classroom_name|day_of_week|period_index)  
**特征数**: 13  
**训练数据**: 11,443 样本 (从清洗后课表提取)

**13 个特征**:
```
course_name_code, course_code_code, teacher_no_code, teacher_name_code,
class_name_code, class_major_code, class_department_code, class_grade,
class_no, student_count, total_hours, course_type_code, required_room_type_code
```

**推理流程**:
1. 编码 task 特征 → 13 维向量
2. LightGBM predict → 3953 维概率分布
3. TopK 概率最高的 resource_key → 解析为 (classroom, day, period)
4. 补充 day/period 覆盖兜底候选 (每种 slot 至少 3 个教室备选)
5. 按 day/period 分散排序，避免候选集中在热门时段

**模型表现**:
- hit@1 = 19%
- hit@10 = 47%
- 新样本测试：对全新组合给分散预测，不过拟合 ✅

**代码位置**: `ml/scheduling_v3/placement_direct.py`, `ml/training/train_v3_placement_direct_model.py`

### Step 3: 模板生成 (Task Plans)

**目标**: 为每个教学任务生成多种可行的周次分布方案。

每个 plan 包含：
- 选中的 resource (classroom, day, period)
- 周次分配 (哪几周上这个 resource)
- 总 sessions = 教学任务课时数

**WeekUsageAllocator**: 
- 保证学期 18 周均匀覆盖
- 每 task 最多 120 个 plan
- 8 线程并行构建

**代码位置**: `ml/scheduling_v3/plan_templates.py`

### Step 4: CP-SAT 全局方案选择

**工具**: Google OR-Tools CP-SAT solver

**问题建模**:
- 变量: 每个 task 选哪个 plan_index (整数变量)
- 硬约束: 同一 (teacher_id, week, day, period) 最多出现一次 (教室/班级同理)
- 软目标: 最大化 sum(plan.quality_score)

**多方案生成**:
- `scheme_count` 控制生成方案数 (默认 3, 最大 20)
- 每个方案独立求解，通过添加 forbidden assignment 约束避免重复
- 如果无法满足 scheme_count，返回已求解的最大数量

**性能与全量压测策略**:
- `FEASIBILITY`: 可行性优先，`scheme_count` 强制按 1 执行，先找首个无冲突方案。
- `QUALITY`: 质量优先，在可行基础上同时优化 Placement 模型分与教师画像满足度。
- `STRESS`: 压测模式，面向 2615~4000+ teaching_task，使用更大的 `placement_top_k`、`raw_plan_count`、`cp_plan_count` 和更长 `solver_time_limit_seconds`。
- CP-SAT 前固定输出 `preflight_report.json`，先检查无候选/无 plan、教师负载、班级负载和房型候选容量风险；明显无解时 fail fast。
- 推荐压测顺序：`preflight` → `FEASIBILITY` first feasible → `QUALITY/STRESS` quality optimization。

**代码位置**: `ml/scheduling_v3/cp_sat_selector.py` (668 行)

### 独立入口: GA 选择器 (`global_plan_selector.py`)

除 CP-SAT 外，还实现了一个 GA 全局选择器作为独立入口（**不被 pipeline 调用**）：
- 染色体: gene_i = plan_index (每个 task 选一个 plan)
- 适应度: 硬冲突数 + quality_score
- 锦标赛选择、精英保留、定向变异
- 用于对比实验和论文消融研究

Pipeline 主链路只用 CP-SAT。

**代码位置**: `ml/scheduling_v3/global_plan_selector.py` (613 行)

---

## API 端点

### `POST /v3/generate` (同步)

```json
{
  "allocation_task_id": 1,
  "top_k": 80,
  "plan_count": 240,
  "scheme_count": 3,
  "solver_time_limit_seconds": 1800.0,
  "generation_mode": "QUALITY"
}
```

返回 `v3_summary.json` 的内容。

### `POST /generate-scheme` (异步 + SSE)

Java 兼容端点，202 Accepted 后通过 `/generate-scheme/{task_uid}/stream` 推送 SSE 进度事件。

**代码位置**: `ml/api/routers/v3.py`

---

## 输出格式

```
data/generated/v3/task_{id}_{timestamp}/
├── placement_candidates.jsonl   # Step 2 输出
├── task_plans.jsonl             # Step 3 输出
├── task_plans_cp.jsonl          # CP-SAT 前按 cp_plan_count 裁剪后的 plans
├── preflight_report.json        # CP-SAT 前轻量可行性诊断
├── schemes.jsonl                # Step 4 最终方案
├── v3_summary.json              # 汇总信息
└── cp_sat_summary.json          # CP-SAT 求解详情
```

**schemes.jsonl** 每行一个方案，`items` 数组包含每条排课记录：
```json
{
  "items": [
    {
      "teaching_task_id": 123,
      "time_slot_id": 1001,
      "classroom_id": 20,
      "week_number": 1,
      "day_of_week": 1,
      "period_index": 2,
      "plan_id": "plan_003",
      "resource_key": "A301|1|2"
    }
  ]
}
```

---

## 训练数据链路

### 数据来源

从清洗后的真实课表 (`data/real-dataset/`) 提取训练样本：

1. 读取 `timetables_clean.jsonl` (45475 行)
2. 关联 teaching_tasks, courses, classrooms, class_groups, teachers
3. 提取每条排课记录的 (task 特征, resource_key) 对
4. 按 `source_key + resource_key` 去重 (避免全学期每周重复过度加权)
5. 输出: `v3_placement_direct_training_samples_clean.csv` (11443 条)

### 模型训练

- 按 `class_name` 分组划分训练/验证集 (GroupShuffleSplit, test=10%)
- LightGBM 参数: objective=multiclass, num_class=3953, num_leaves=127
- 产出: `models/v3/placement_direct_model.txt` + schema + labels

**代码位置**: `ml/training/build_v3_placement_direct_training_data.py`, `ml/training/train_v3_placement_direct_model.py`

---

## 数据清洗链路

所有原始数据经过统一清洗脚本处理，输出 `_clean` 后缀文件：

| 原始文件 | 清洗后 | 主要操作 |
|---------|--------|---------|
| classrooms.jsonl | classrooms_clean.jsonl | 去除非普通教室/机房，修正名称 |
| courses.jsonl | courses_clean.jsonl | 删除实践课，标准化课程类型 |
| teaching_tasks.jsonl | teaching_tasks_clean.jsonl | 剔除 342 条实践课任务 |
| timetables.jsonl | timetables_clean.jsonl | 关联清洗后数据，剔除孤立记录 |

导入 DB: `scripts/import_clean_to_db.py` — 6 张表一键导入。

---

## 当前局限与后续方向

### 已确认问题
- 教师画像已落地为独立分析层，但尚未进入 Placement Model 特征或 CP-SAT 目标函数
- 当前只排专业课（2615 tasks），公共课（620 tasks）未接入
- 反馈闭环尚未建成：人工调课记录未回写训练数据

### 后续重点
1. **两遍方案落地**: Pass 1 公共课 (beam search) + Pass 2 专业课 (CP-SAT)
2. **反馈闭环**: 人工调课记录回写训练数据，placement model 增量重训
3. **教师画像接入**: 在 placement model 特征中增加画像特征
4. **模型迭代**: 积累更多反馈后重训 placement model，提升 hit@k

---

## 与 V1/V2 的关系

| 维度 | V1 (GA) | V2 (Beam Search) | V3 (CP-SAT) |
|------|---------|------------------|-------------|
| 搜索方式 | GA 直接搜 slot×room | Beam 逐步构造 | CP-SAT 全局约束求解 |
| 模型角色 | 局部评分辅助 GA | 指导 beam 选择 | 生成候选方案 (placement) |
| 候选粒度 | 单次放置 | 单次放置 | 完整 task plan |
| 多方案 | GA 循环 | 固定 1 套 | CP-SAT 独立求解 N 套 |
| 硬约束 | fitness 惩罚 | 构造过滤 + 修复 | CP-SAT 硬约束建模 |
| 数据规模 | 100 tasks | 2957 tasks | 2615 tasks |

V1 (`ml/archive/v1_scheduling/`) 和 V2 (`ml/archive/v2_scheduling/`, `ml/archive/v2_channels/`) 已归档。

---

## 代码索引

### 主链路 (pipeline 直接调用)

| 模块 | 文件 | 职责 |
|------|------|------|
| Pipeline | `ml/scheduling_v3/pipeline.py` | 全链路编排 + 内联 placement 推理 (645 行) |
| Placement Model | `ml/scheduling_v3/placement_direct.py` | LightGBM 多分类加载与推理 (115 行) |
| Task Plans | `ml/scheduling_v3/plan_templates.py` | 周次方案构建 + WeekUsageAllocator (433 行) |
| CP-SAT Selector | `ml/scheduling_v3/cp_sat_selector.py` | 全局方案选择 ★ 主力 (668 行) |

### 独立入口 (不被 pipeline 调用)

| 模块 | 文件 | 职责 |
|------|------|------|
| Placement Candidates CLI | `ml/scheduling_v3/placement_candidates.py` | 独立 placement 候选生成脚本（自带批量推理 + 兜底）(878 行) |
| GA Selector | `ml/scheduling_v3/global_plan_selector.py` | GA 备选方案选择（独立入口，对比实验用）(613 行) |

### 训练与数据

| 模块 | 文件 | 职责 |
|------|------|------|
| Training Data | `ml/training/build_v3_placement_direct_training_data.py` | 训练数据构建 (264 行) |
| Model Training | `ml/training/train_v3_placement_direct_model.py` | 模型训练 (207 行) |
| API Router | `ml/api/routers/v3.py` | HTTP 端点 (140 行) |
| DB Import | `scripts/import_clean_to_db.py` | 数据导入脚本 |

---

## 相关文档

- [LightGBM 模型训练架构](./03-LightGBM模型训练架构设计.md) — V3 placement model 的训练方法论
- [训练数据链路](./05-模型训练数据链路设计.md) — 真实课表 → 训练样本的完整链路
- [数据闭环与画像演进](./12-数据闭环与画像演进设计.md) — 反馈循环与模型迭代
- [双通道排课架构 (archive)](../archive/14-双通道排课架构设计.md) — V3 两遍方案的拓扑分析来源
