# backend/python — Python 侧代码布局

> 更新时间：2026-08-23
> 所有模块统一从本目录以 `python -m <package>.<module>` 方式运行。正式排课由 FastAPI
> 持久作业入口启动该命令；Java 只调用 HTTP，不依赖本机 Python 虚拟环境。

## 目录职责

```text
backend/python/
├── app/           # FastAPI 服务 (health) + DB 会话/仓储 (app.db.session 被全部包共用)
├── scheduler/     # ★ 排课引擎: pattern → 周模板 → DB draft → 校验 → 入库
├── ingest/        # 课表导入 + 历史训练闭环 (Excel 解析 → review → 训练样本 → 重训模型)
├── scripts/       # 一次性数据工具 (backfill / audit / 实验脚本), 直接 python scripts/x.py 运行
└── tests/         # unittest (python -m unittest discover -s tests -t .)
```

## 环境

```bash
cd backend/python
uv sync                  # 依赖以 pyproject.toml 为准 (uv.lock 锁定)
brew install libomp      # macOS: lightgbm 的 OpenMP 运行时
```

## scheduler/ — 排课引擎

```text
run_pipeline.py               全链路编排 (FastAPI 持久作业的执行入口)
pattern_builder.py            课时 → (每周频次, 持续周数) 查表
generate_synthetic_data.py    直接多班任务 + 教室分层必要容量预检
phase_scheduler.py            ★ 动态周模板引擎: 绝对周占位 → 全枚举合法候选
                              → 有界局部重排 → 动态模板压缩 → 冲突/课时终审
placement_single_model.py     LightGBM 单模型: 任务特征 → TopK (教室|day|period), 分数只作软偏好
paths.py                      共享数据/模型路径常量
clean_training_samples.py     训练样本清洗
fetch_allocation_teaching_tasks.py   从 DB 拉取排课任务
export_template_cover_db_draft.py    cover → DB draft, week 映射使用显式 week_numbers
export_template_as_scheme.py         cover → allocation_scheme (前端方案视图)
import_db_draft_to_mysql.py          DB draft 入库
query_db_draft_timetable.py          按显式动态模板映射展开周课表 + 换周模拟
validate_patterns.py / validate_db_draft_export.py   环节校验
```

时间坐标统一为每天10个45分钟原子小节：上午1-4、下午5-8、晚上9-10。
自动排课默认只使用工作日1-8，晚间和周末保留给人工操作。排课先在绝对周次上判断
教师、班级和教室占用；课程完成后立即释放后续周资源，最后再把课表相同的周压缩为
动态模板。每张模板携带明确的 `week_numbers`。

一键跑排课（不入库）：

```bash
cd backend/python && source .venv/bin/activate
python -m scheduler.run_pipeline --allocation-task-id 1 --total-weeks 18 --top-k 300
```

加 `--train-model` 才会重训并启用模型引导；普通第一阶段运行保持 rules-only。
加 `--import-db [--truncate-db]` 入库。旧模型若没有 `atomic-45m-10-v1` 时间轴契约，
加载时会被拒绝并自动降级到规则候选。
运行产物在 `backend/data/pipeline/v3.5/runs/<run_id>/`（数据目录沿用 v3.5 命名，与代码包名无关）。

第一阶段模拟链路（不读数据库、不启用 Placement Model）：

```bash
python -m scheduler.run_synthetic_pipeline --output-dir /tmp/edu-flow-run
python -m scheduler.run_synthetic_pipeline --profile formal-mix --output-dir /tmp/edu-flow-formal-mix
python -m scheduler.synthetic_test_suite
python -m unittest tests.test_synthetic_scheduler
```

`balanced` 默认使用 1964 条教学任务，是工作日 1–8 全部排完的多种子验收
基线。`formal-mix` 在可行数据上加入助教、教师禁排、`allowed_weeks`、固定教室
和候选教室。`constrained` 是必须显式进入 `needs_manual_review` 的资源压力场景。
教室预检按房型和座位分界比对 18 周自动排课域的需求/供给；“通过”是
必要条件，不代表已经证明整个实例可排。

管理端“模拟实验台”通过 `/api/ml/simulation/preview` 生成并持久化一份带
`simulation_id` 的输入，随后 `/run` 必须复用同一份输入。产物默认保存在系统临时目录的
`edu-flow-ai-simulations/<simulation_id>/`；容器内使用
`/var/lib/edu-flow-ai/simulations/` 持久卷。完整验收口径见
`docs/implementation/09-第一阶段模拟排课验收.md`。

旧分段原型（仅兼容历史实验，不是正式主链）：

```bash
python -m scheduler.phase_prototype
```

模型训练与推理样例：

```bash
python -m scheduler.placement_single_model train --data ../models/v3.5/placement/clean_training_samples.jsonl --rounds 160
python -m scheduler.placement_single_model predict-sample --index 0 --top-k 20
```

## ingest/ — 课表导入与历史训练闭环

```text
parse_schedule_excel.py            单份课表 Excel → CSV
csv_to_jsonl.py                    CSV → JSONL
batch_process_schedule_imports.py  批量解析 (Java ImportReviewService 调用)
analyze_schedule_import.py         解析结果 vs DB 基础数据比对
prepare_import_review.py           生成人工 review 清单
apply_import_review.py             应用 review 结果入库 (Java ImportReviewService 调用)
extract_training_samples.py        导入课表 → 训练样本
build_history_training_dataset.py  历史课表训练集构建
audit_history_training_dataset.py  训练集审计
build_test_schedule_dataset.py     测试集构建
train_from_history.py              历史重训编排 (Java ModelHistoryTrainingService 调用)
```

## Java / Python 正式排课契约

`V35TemplateGenerationService` 调用 `POST /api/ml/pipeline/jobs`，Python 在
`schedule_generation_run` 中原子预留任务、持久化状态和日志，再以
`python -m scheduler.run_pipeline` 执行。Java 重启后仍可通过
`GET /api/ml/pipeline/jobs/latest` 查询同一作业；最终状态为
`SUCCESS / NEEDS_MANUAL_REVIEW / BLOCKED / FAILED`。

第一阶段请求固定 `trainModel=false`、`importDb=true`、`truncateDb=false`。
模板草案与候选方案在一个数据库事务中写入，任一导入步骤失败都会整体回滚。
历史导入和模型训练模块仍是独立工具，不属于这条正式排课作业链。

## 模型契约

```text
input  = teaching-task 特征 (course/teacher/class/hours/room_type)
output = TopK 周模板放置: classroom_name | day_of_week | period_index + score
约束   = 模型分数只影响格子选择顺序 (软偏好), 永远不裁剪可行域;
         硬约束 (主讲/助教、所有合班班级、教室、容量、不可用时间和允许周次)
         由排课器负责；模型不是可行性来源
```

模型文件：`backend/models/v3.5/placement_single/`。

## 数据目录

```text
backend/data/raw/        原始 Excel
backend/data/parsed/     解析产物 (schedule_imports*, 数据集)
backend/data/pipeline/   排课 pipeline 运行产物 (runs/<run_id>/)
backend/models/          训练好的模型 + 训练样本
```
