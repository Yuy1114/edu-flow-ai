# 教师画像只排序候选，不改变可行域

教师画像（历史统计派生 + 教师声明 + 反馈证据）进入排课引擎的方式是**候选排序**，不是第四类硬约束。`scheduler/teacher_preferences.py` 对任务与周掩码可用的 `(day, start)` 组合按偏好打一个 0~1 的分，`find_spot` 先试分高的格子；教室池按偏好房型重排但**一间都不裁**。可行性仍然完全由既有硬约束判定（`base_free` / `room_free`：教师、班级、教室互斥、不可用矩阵、房型与容量、单日节数上限 `TEACHER_DAY_CAP = 6`）。画像永远压不过课时守恒：排序只决定先试哪个格子，排不下照样进 `unresolved`，不做任何"为满足偏好而少排一次课"的让步。

一个任务有多位教师（主讲 + 助理）时按**逐维度取最小值**合并：只有对所有教师都合意才算好格子，与硬约束"任一教师被占即不可行"同向。

读不到画像（payload 缺失、字段不认识、取值越界、教师不在 payload 里）就退回引擎原有确定性顺序，行为与接入前逐位相同：这条由 `tests/test_teacher_preference_ranking.py` 的 `NoPreferenceMeansNoChangeTest` 与 `HardConstraintsStillWinTest` 看守（后者断言开关画像前后 `audit_dynamic_schedule` 与 `final_hour_audit` 逐字段相等）。

## Consequences

- 可消融：同一批任务跑两次（带画像 / 不带画像），`cover-report.json` 的 `profile_satisfaction` 给出 `avg_preference_score`、`low_satisfaction_count` 与逐教师分量，"画像有没有用"是实测数字而不是说法。
- 可解释：分量名与 Java 侧方案满意度一致（`early_period` / `late_period` / `preferred_weekday` / `preferred_period` / `daily_load` / `room_type`），生成侧与评估侧能放在同一页对照。两个分数分开记：`satisfaction_score` 六分量等权（对齐 Java，未声明维度记 1.0），`preference_score` 只对已声明维度取平均并作为低满意判定口径。
- 不新增环境变量、不新增权重开关：权重只有一处常量表 `WEIGHTS`（含排序侧独有的 `compactness`），改口径必须改代码，且报告里带 `weights`。
- 画像只有一条写入路径：Java `TeacherProfileDocumentService` 装配 `final_profile` 后随作业 payload 传给 Python，并落盘 `pipeline_runs/<run>/teacher_profiles.json`。画像基线文件缺失时退化为"只有教师声明画像"，排课链路不会因为画像文件不在而停摆。
- 已知口径差：声明侧 `preferredMaxDailyHours` 是"每天最多几小时"，而 `max_daily_lessons` 在评估侧按"课次"比较。生成侧沿用既有比较口径以保持两侧可比；要严格化应在声明侧换算（小时 ÷ 每次课时）后再落库，不在排课引擎里做隐式换算。
- 目前只有 `preferred_periods` 有外部来源（反馈聚合），`preferred_room_types` 还没有任何生产方：两个维度在引擎里已实现，但缺值时不参与打分（不会被当成 1.0 稀释其他维度）。
