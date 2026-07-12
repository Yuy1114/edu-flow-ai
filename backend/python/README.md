# backend/python — Python 侧代码布局

> 更新时间：2026-07-12
> 所有模块统一从本目录以 `python -m <package>.<module>` 方式运行（Java ProcessBuilder 同样如此调用）。

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
run_pipeline.py               全链路编排 (Java V35TemplateGenerationService 调用入口)
pattern_builder.py            课时 → (每周频次, 持续周数) 查表
phase_scheduler.py            ★ 分段周模板引擎: 合班 → 分段装箱 → 段内放格(模型软偏好
                              + 全枚举兜底 + 搬迁修复) → 冲突/课时守恒自检
placement_single_model.py     LightGBM 单模型: 任务特征 → TopK (教室|day|period), 分数只作软偏好
paths.py                      共享数据/模型路径常量
clean_training_samples.py     训练样本清洗
fetch_allocation_teaching_tasks.py   从 DB 拉取排课任务
export_template_cover_db_draft.py    cover → 四表 JSONL, week 映射按各模板 week_budget 铺开
export_template_as_scheme.py         cover → allocation_scheme (前端方案视图)
import_db_draft_to_mysql.py          DB draft 入库
query_db_draft_timetable.py          按周展开(遵守相对掩码) + 换周模拟
validate_patterns.py / validate_db_draft_export.py   环节校验
```

课时守恒的相对掩码语义: fragment 带 `duration_weeks`, 展开第 w 周时仅当 w 在其模板
映射周中的出现序号 ≤ duration_weeks 才生效; 跨段课在后段模板只承担扣除前段预算后的
份额。换周(交换 schedule_template_week 行)不破坏该语义。Java 侧
`AllocationTemplateMapper.findWeekTimetable*` 用同一规则过滤。

一键跑排课（不入库）：

```bash
cd backend/python && source .venv/bin/activate
python -m scheduler.run_pipeline --allocation-task-id 1 --total-weeks 18 --top-k 300 --max-templates 8
```

加 `--train-model` 重训单模型；加 `--import-db [--truncate-db]` 入库。
运行产物在 `backend/data/pipeline/v3.5/runs/<run_id>/`（数据目录沿用 v3.5 命名，与代码包名无关）。

分段原型（读取最近一次 run 的 pattern 数据）：

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

## Java 调用契约

Java 侧以 `backend/python` 为工作目录、`.venv/bin/python` 为解释器，调用以下模块：

| Java 服务 | Python 模块 |
|-----------|-------------|
| `V35TemplateGenerationService` | `-m scheduler.run_pipeline` |
| `ModelHistoryTrainingService` | `-m ingest.train_from_history` |
| `ImportReviewService` | `-m ingest.batch_process_schedule_imports` / `-m ingest.apply_import_review` |

改动这些模块的 CLI 参数时必须同步改 Java。

## 模型契约

```text
input  = teaching-task 特征 (course/teacher/class/hours/room_type)
output = TopK 周模板放置: classroom_name | day_of_week | period_index + score
约束   = 模型分数只影响格子选择顺序 (软偏好), 永远不裁剪可行域;
         硬约束 (教师/班级/教室冲突, 容量) 由排课器负责
```

模型文件：`backend/models/v3.5/placement_single/`。

## 数据目录

```text
backend/data/raw/        原始 Excel
backend/data/parsed/     解析产物 (schedule_imports*, 数据集)
backend/data/pipeline/   排课 pipeline 运行产物 (runs/<run_id>/)
backend/models/          训练好的模型 + 训练样本
```
