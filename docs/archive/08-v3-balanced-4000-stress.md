# V3 4000 量级均衡压测链路

目标是在不改业务主链路的前提下，构造约 4000 个均衡 teaching tasks，并让
V3 AUTO 只执行 `FIRST_FEASIBLE → QUALITY_OPTIMIZATION`，跳过
`DIVERSITY_SEARCH`，避免多方案搜索把链路拖到 30 分钟以上。

## 推荐入口：页面创建并启动

推荐从管理后台“分课任务管理”页面操作，不再要求直接运行
`ml/scripts/v3_balanced_stress.py run`：

1. 点击 `创建 4000 压测任务`。
   - 默认选择 `快速质量模式`：
     `AUTO_QUALITY`，执行
     `FIRST_FEASIBLE → QUALITY_OPTIMIZATION`。
   - 如需完整三步，手动选择 `完整优化模式`：
     `AUTO_FULL`，执行
     `FIRST_FEASIBLE → QUALITY_OPTIMIZATION → DIVERSITY_SEARCH`。
     页面会二次确认，避免误触长跑。
2. 页面会调用后端 `POST /api/allocation-tasks/stress/balanced-4000`，
   写入 `allocation_task`、4000 条均衡 `teaching_task`、班级关联、
   任务关联和生成配置；请求体中的 `mode` 会写入
   `generation_mode=AUTO_QUALITY` 或 `AUTO_FULL`。
3. 创建成功后页面展示 `allocationTaskId`、`64/64/16` 生成配置和
   教师/班级/课程分布摘要。
4. 点击 `启动 4000 压测生成`，复用现有
   `POST /api/allocation-tasks/{id}/generate-async`。
5. 页面通过现有
   `GET /api/allocation-tasks/{id}/generation-stream` SSE 展示
   `stage`、`message`、`progress`、`solver_status`、`summary_path`、
   `output_dir`、`error_diagnosis` 和 `stage_strategy`。

后端生成主链路仍走现有 Java → ML FastAPI HTTP/SSE → V3 pipeline，
不是 Java shell 调脚本。脚本保留为 dry-run、CLI 和输出检查工具。

## 参数 Profile

默认 profile 位于 `ml/scripts/v3_balanced_stress.py`：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `task_count` | `4000` | 生成 4000 个 teaching tasks |
| `generation_mode` | `AUTO_QUALITY` | 默认快速质量模式，只跑首个可行解 + 质量优化 |
| `max_auto_stage` | `QUALITY_OPTIMIZATION` | 显式跳过 diversity |
| `scheme_count` | `1` | 只保留 1 个最终方案 |
| `placement_top_k` | `64` | 4000 首轮以可行性优先，保留更宽资源候选 |
| `raw_plan_count` | `64` | 每任务生成 64 个原始 plans，避免候选覆盖过窄 |
| `cp_plan_count` | `16` | 4000 任务约 64000 个 CP-SAT 布尔变量，换取更稳的 first feasible |
| `solver_time_limit_seconds` | `1800` | quality 阶段上限 30 分钟 |
| `allowed_periods` | `1,2,3,4,5` | 给 4000 压测保留晚间节次容量 |

`FIRST_FEASIBLE` 阶段仍使用 pipeline 内部上限：
`max(30, min(solver_time_limit_seconds, 300))`，即默认最多 300 秒。
当前 `AUTO` / `AUTO_QUALITY` 默认截断到 `QUALITY_OPTIMIZATION`；如确实
需要多方案搜索，使用页面的 `完整优化模式`，或 API 传
`generation_mode=AUTO_FULL` / `max_auto_stage=DIVERSITY_SEARCH`。

## AUTO 阶段策略与观测

后端会把 4000 页面模式显式传给 ML pipeline：

- `AUTO_QUALITY`：
  `max_auto_stage=QUALITY_OPTIMIZATION`，`skip_diversity=true`
- `AUTO_FULL`：
  `max_auto_stage=DIVERSITY_SEARCH`，`skip_diversity=false`

V3 pipeline 每个 CP-SAT 阶段会在 progress/SSE 中输出
`stage_strategy` 和可读 `strategy` 文本，前端诊断面板展示为
`stage_strategy`。默认阶段策略：

| 阶段 | workers | 目标 |
| --- | ---: | --- |
| `FIRST_FEASIBLE` | `4` | 快速寻找首个无冲突可行解 |
| `QUALITY_OPTIMIZATION` | `8` | 在可行基础上优化模型分和教师画像目标 |
| `DIVERSITY_SEARCH` | `8` | 搜索多方案并进一步优化候选覆盖 |

`stage_strategy` 同时包含
`time_limit_seconds`、`top_k`、`raw_plan_count`、`cp_plan_count`、
`scheme_count`、`objective_mode` 和说明。CP-SAT selector 的
`num_search_workers` 已由固定 `8` 改为 pipeline 每阶段传入。

4000 压测的首轮目标是先排除“候选太窄导致的假 INFEASIBLE”。旧的
`placement_top_k=24/raw_plan_count=24/cp_plan_count=6` 只有约 24000 个
CP-SAT 布尔变量，preflight 可能显示每个任务都有 plan，却仍因全局冲突集中
导致 `FIRST_FEASIBLE` 失败。新默认会提高变量数和 task-plan 成本，但优先
保证候选覆盖，避免把覆盖不足误判为数据本身不可排。

为兼容已经写入旧 profile 的压测任务，pipeline 在 `FEASIBILITY` 且
`task_count >= 4000` 时会把首轮候选下限提升到 `64/64/16`。`QUALITY` 阶段
仍使用生成配置或脚本默认值，不额外强制放大。

## CLI 生成数据（辅助）

脚本仍可用于 dry-run，看教师、班级、课程三者分布是否均衡：

```bash
python ml/scripts/v3_balanced_stress.py prepare
```

如需绕过页面做 CLI 写库：

```bash
python ml/scripts/v3_balanced_stress.py prepare --execute
```

如果需要重建同名压测任务：

```bash
python ml/scripts/v3_balanced_stress.py prepare --execute --replace
```

脚本会创建：

- `allocation_task`：默认名称 `v3-balanced-stress-4000`
- `allocation_task_generation_config`：写入 4000 profile 参数
- `teaching_task`：按教师、班级、课程轮转均衡生成
- `teaching_task_class_group` / `allocation_task_teaching_task` 关联

## 跑首个可行解

如果只想单独验证 first feasible：

```bash
python ml/scripts/v3_balanced_stress.py run \
  --allocation-task-id <TASK_ID> \
  --generation-mode FEASIBILITY \
  --solver-time-limit-seconds 300 \
  --scheme-count 1
```

看输出目录中的：

- `v3_summary.json`
- `preflight_report.json`
- `cp_sat_summary.json`

## CLI 跑 AUTO 到高质量方案（辅助）

页面链路优先；如需单独验证 ML pipeline，可用脚本：

```bash
python ml/scripts/v3_balanced_stress.py run \
  --allocation-task-id <TASK_ID>
```

等价于：

```bash
python ml/scripts/v3_balanced_stress.py run \
  --allocation-task-id <TASK_ID> \
  --generation-mode AUTO_QUALITY \
  --max-auto-stage QUALITY_OPTIMIZATION \
  --skip-diversity \
  --top-k 64 \
  --plan-count 64 \
  --scheme-count 1 \
  --solver-time-limit-seconds 1800
```

该 AUTO 链路会执行：

1. `FIRST_FEASIBLE`：快速确认存在无冲突方案。
2. `QUALITY_OPTIMIZATION`：在可行基础上优化模型分和教师画像目标。
3. `DIVERSITY_SEARCH`：记录为 `SKIPPED`，不跑多方案搜索。

## 查看耗时和结果

AUTO 输出 summary：

```bash
python ml/scripts/v3_balanced_stress.py inspect-output \
  data/generated/v3/task_<TASK_ID>_<TIMESTAMP>/auto_summary.json
```

单阶段输出 summary：

```bash
python ml/scripts/v3_balanced_stress.py inspect-output \
  data/generated/v3/task_<TASK_ID>_<TIMESTAMP>/quality/v3_summary.json
```

重点检查：

- `auto_summary.json.stages[*].runtime_s`
- `auto_summary.json.best_stage`
- `cp_sat_summary.json.solver_status`
- `cp_sat_summary.json.variable_count`
- `cp_sat_summary.json.candidate_coverage_diagnosis`
- `v3_summary.json.conflicts`
- `preflight_report.json.no_plan_task_count`

如果 `cp_sat_summary.json.solver_status=INFEASIBLE`，且
`preflight_no_candidate_task_count=0`、`preflight_no_plan_task_count=0`，
`candidate_coverage_diagnosis` 会提示候选集覆盖不足或冲突集中。此时优先
提高 `placement_top_k`、`raw_plan_count` 和 `cp_plan_count`，不要按“数据无
候选”方向排查。

## API 方式

`/api/ml/v3/generate` 和 `/api/ml/generate-scheme` 已支持：

```json
{
  "task_id": 123,
  "generation_mode": "AUTO_QUALITY",
  "max_auto_stage": "QUALITY_OPTIMIZATION",
  "skip_diversity": true
}
```

`generation_mode=AUTO` / `AUTO_QUALITY` 都会把 AUTO 截断到
`QUALITY_OPTIMIZATION`；`skip_diversity=true` 是显式保险。如果要恢复旧的
多方案搜索，传 `generation_mode=AUTO_FULL` 或
`max_auto_stage=DIVERSITY_SEARCH`。
