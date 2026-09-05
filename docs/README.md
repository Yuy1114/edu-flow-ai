# Edu-Flow-AI 文档索引

> 更新时间：2026-08-23
> 原则：项目文档统一维护在本仓库 `docs/` 下。

> 当前实现口径以仓库根目录 `CONTEXT.md`、`docs/adr/0001-*`、
> `docs/adr/0002-*`、`docs/adr/0003-*` 和 `architecture/22-V3.5-*` 为准。旧的 GA/CP-SAT、
> 固定 T1/T2 说明属于历史方案或待重写论文草稿，不能用来描述当前代码。

---

## 文档结构

```text
docs/
├── README.md                                    ← 本文件
├── architecture/                                ← 架构设计
│   ├── 22-V3.5-模板化排课落库设计.md             ← ★ 当前排课架构 (V3.5 周模板)
│   ├── 18-V3-教师画像MVP设计.md                  ← 教师画像分析层 ★
│   ├── 03-LightGBM模型训练架构设计.md
│   ├── 04-训练样本事件采集架构设计.md
│   ├── 05-模型训练数据链路设计.md
│   ├── 06-真实课表导入字段模板.md
│   ├── 07-AI生成课表人工筛选标准.md
│   ├── 08-模型消融实验设计方案.md
│   ├── 10-LightGBM选型与模型对比说明.md
│   ├── 12-数据闭环与画像演进设计.md
│   └── 02-教师画像作用路径设计.md
├── implementation/                              ← 实现说明
│   ├── 02-教师画像JSONL快照接入说明.md
│   ├── 03-排课链路验证与排障说明.md
│   ├── 04-scoring-config-fields-migration.sql
│   ├── 05-真实课表数据导入流程.md
│   ├── 09-第一阶段模拟排课验收.md
│   └── 10-第一阶段正式排课链路验收.md
├── archive/                                     ← 历史存档
│   ├── README.md
│   ├── 01-排课架构设计.md                        (V1 GA)
│   ├── 09-GA编码与适应度函数设计.md
│   ├── 11-核心链路论文版总设计.md
│   ├── 14-双通道排课架构设计.md                   (V2 启发 V3)
│   ├── 15-基于候选空间压缩...md                   (V2.5 候选池 GA)
│   ├── 16-实时排课简化方案.md                     (V2 Beam Search)
│   ├── 01-GA排课生成链路实现说明.md
│   └── 13-评分体系与约束分层设计.md               (V2 GA scoring)
├── thesis/
│   ├── 01-论文目录与章节要点.md
│   ├── 02-答辩PPT大纲.md
│   ├── 03-核心图清单与草图说明.md
│   ├── 04-核心图Mermaid草稿.md
│   ├── 05-论文与答辩材料待办清单.md
│   └── 06-GA编码设计技术选型依据.md
├── feedback/
│   └── 01-排课真实数据验收反馈.md
└── roadmap/
    ├── 01-训练样本收集优先路线.md
    ├── 02-理论与实验设计推进路线.md
    └── 03-毕设最终系统剩余开发清单.md
```

---

## 文件职责

| 文档 | 职责 | 状态 |
|------|------|------|
| **architecture/19-毕设最终系统架构设计.md** | 毕设产品愿景；其中旧 CP-SAT 实现描述已失效 | ⚠️ 待按动态模板基线重写 |
| **architecture/20-教师画像反馈信号接入点设计.md** | ★ 教师画像 Phase 2：反馈事件接入点与画像聚合方案 | ✅ 设计完成 |
| **architecture/22-V3.5-模板化排课落库设计.md** | ★ 当前架构：绝对周占位 + 动态周模板 + 模板化落库 | ✅ 当前 |
| **architecture/18-V3-教师画像MVP设计.md** | ★ V3 教师画像：历史课表画像提取 + 课表满足度分析 | ✅ MVP |
| archive/17-V3-CP-SAT排课架构设计.md | V3：Placement Model + CP-SAT 全局方案选择（代码已删除） | 📦 已归档 |
| archive/21-教师画像进入CP-SAT接入点设计.md | 教师画像进 CP-SAT objective（随 V3 归档） | 📦 已归档 |
| architecture/03-LightGBM模型训练架构设计.md | 训练闭环设计（规则冷启动→反馈重训），V3 placement model 的训练方法论 | ⚠️ 需更新 |
| architecture/04-训练样本事件采集架构设计.md | 事件表、行为快照、调整相消、人工标注 | ⚠️ 需更新 |
| architecture/05-模型训练数据链路设计.md | 真实课表→片段级样本→标签权重→sigmoid归一化 | ⚠️ 需更新 |
| architecture/06-真实课表导入字段模板.md | 学校真实课表导入字段、标准化 | ✅ 仍适用 |
| architecture/07-AI生成课表人工筛选标准.md | 方案级/片段级人工筛选标准 | ✅ 仍适用 |
| architecture/08-模型消融实验设计方案.md | 评分器消融实验分组 | ⚠️ 需适配 V3 |
| architecture/10-LightGBM选型与模型对比说明.md | LightGBM vs RF/XGBoost/深度学习 | ✅ 仍适用 |
| architecture/12-数据闭环与画像演进设计.md | 数据获取、特征工程、数据漂移、画像演进 | ⚠️ 需更新 |
| architecture/02-教师画像作用路径设计.md | 教师画像在排课中的作用路径 | ⚠️ V3 尚未接入 |
| implementation/02-教师画像JSONL快照接入说明.md | 画像快照导出与传递 | ⚠️ 待 V3 适配 |
| implementation/03-排课链路验证与排障说明.md | 本地验证命令、常见问题 | 🔴 已过时 (V2) |
| implementation/09-第一阶段模拟排课验收.md | 无真实数据清洗前提下的模拟链路、接口和验收标准 | ✅ 当前 |
| implementation/10-第一阶段正式排课链路验收.md | 真实 MySQL、持久作业、草案人工复核、确认发布与正式课时总账 | ✅ 当前 |
| implementation/05-真实课表数据导入流程.md | XLS→JSONL→MySQL 管道 | ✅ 仍适用 |
| implementation/06-allocation-item-teacher-profile-fields-migration.sql | allocation_item 教师画像解释字段迁移 | ✅ Phase 3 |
| thesis/* | 论文与答辩材料 | ⚠️ 需更新为 V3 |
| feedback/01-排课真实数据验收反馈.md | V2 验收中的非阻塞问题 | ⚠️ 部分已修复 |
| roadmap/01-训练样本收集优先路线.md | 样本收集路线 | ⚠️ 需更新 |
| roadmap/02-理论与实验设计推进路线.md | 理论实验推进 | ⚠️ 需更新 |
| roadmap/03-毕设最终系统剩余开发清单.md | 从最终架构反推的开发 TODO | ✅ 当前路线图 |

---

## 当前架构边界

```text
核心思路: 绝对周占位 → 已完成任务释放资源 → 按周课表签名派生动态模板

输入接口: Java 仅传 allocation_task_id
时间坐标: 每天10个45分钟原子小节；自动默认工作日1-8，9-10和周末保留人工使用
决策粒度: 每个 teaching_task 按 pattern 在 (week, day, period, classroom) 上占位
求解方式: 硬约束全枚举 + 贪心放置 + 1~2任务局部重排；失败只标待人工，不证明无解
落库:     schedule_template / _week / _fragment / _fragment_slot 及教师、班级多值关系表
输出:     模板落库 → 前端按周展开展示

模型:     第一阶段 rules-only；LightGBM 以后只排序合法候选，旧时间轴模型会被拒绝并降级
```

正式链路：`allocation_task_id` → Java `V35TemplateGenerationService` → Python 持久化 HTTP 作业 →
`scheduler.run_pipeline` → pattern 构建 → 绝对周排布 → 动态模板草案 → DB 原子事务入库 →
前端精确周次人工编辑/重审计 → 确认物化为 `course_assignment` → 多条件正式课表与课时终审。
Java 不再依赖本机 `.venv` 或进程内任务状态；作业状态和明确阻塞原因保存在数据库中。
Python 侧代码布局见 `backend/python/README.md`（scheduler = 排课引擎，ingest = 导入与训练闭环）。

领域契约优先看根目录 `CONTEXT.md` 和 `docs/adr/`；实现细节看
`docs/architecture/22-V3.5-*`。`architecture/19-*` 与 `thesis/` 中仍有旧方案文字，
在完成论文重写前仅作为产品愿景和写作素材；`docs/archive/` 为历史参考。
