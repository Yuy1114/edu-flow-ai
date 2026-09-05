import { useModelTraining } from "../hooks/useModelTraining";

const HISTORY_TRAINING_DIR = "backend/data/raw/history_training";
const DATASET_TABLES = [
  { value: "teaching_tasks", label: "教学任务" },
  { value: "timetable_occurrences", label: "课表片段" },
  { value: "courses", label: "课程" },
  { value: "teachers", label: "教师" },
  { value: "classrooms", label: "教室" },
  { value: "class_groups", label: "班级" },
];

const FIELD_LABELS: Record<string, string> = {
  source_semester: "学期",
  source_schedule: "来源课表",
  course_id: "课程ID",
  course_code: "课程代号",
  course_name: "课程",
  teacher_name: "教师",
  class_name: "班级",
  class_names: "合班",
  total_hours: "课时",
  required_hours: "课时",
  classroom_name: "教室",
  classroom_type: "类型",
  day_of_week: "星期",
  period_index: "45分钟节次",
  week_index: "周次",
  student_count: "人数",
  capacity: "容量",
  schedulable: "可排",
  exclude_reason: "排除原因",
};

const TABLE_COLUMNS: Record<string, string[]> = {
  teaching_tasks: ["source_semester", "course_id", "course_code", "course_name", "teacher_name", "class_name", "total_hours", "required_room_type", "schedulable", "source_schedule"],
  timetable_occurrences: ["source_semester", "class_name", "course_id", "course_code", "course_name", "teacher_name", "classroom_name", "week_index", "day_of_week", "period_index", "source_schedule"],
  courses: ["source_semester", "course_id", "course_code", "course_name", "required_hours", "course_type", "required_room_type", "schedulable", "source_schedule"],
  teachers: ["teacher_name", "department", "title", "raw_source"],
  classrooms: ["classroom_name", "classroom_type", "capacity", "status", "raw_source"],
  class_groups: ["source_semester", "class_name", "major", "department", "grade", "student_count", "source_schedule"],
};

function StatCard({ label, value }: { label: string; value: string | number }) {
  return <div className="card bg-base-100 shadow-sm"><div className="card-body p-4 text-center"><div className="text-2xl font-bold">{value}</div><div className="text-xs text-base-content/50 mt-1">{label}</div></div></div>;
}

function fieldLabel(field: string) {
  return FIELD_LABELS[field] || field;
}

function compactValue(value: unknown) {
  const text = String(value ?? "");
  return text.length > 90 ? text.slice(0, 90) + "..." : text || "-";
}

function displayCell(row: Record<string, string>, column: string) {
  if (column === "class_name" && row.class_names) return row.class_names;
  return row[column];
}

export default function ModelTrainingManager() {
  const t = useModelTraining();
  const datasetColumns = (TABLE_COLUMNS[t.datasetTable] || t.dataset?.columns || []).filter(col => t.dataset?.columns?.includes(col));
  const totalPages = Math.max(1, Math.ceil((t.dataset?.total || 0) / t.datasetSize));

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2>模型训练中心</h2>
          <p className="text-sm text-base-content/50 mt-1">反馈事件 → 样本构造 → LightGBM 重训 → 模型版本更新</p>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-ghost btn-sm" disabled={t.eventLoading} onClick={() => t.loadEventSummary()}>刷新事件</button>
          <button className="btn btn-ghost btn-sm" disabled={t.feedbackLoading} onClick={() => t.generateFeedback()}>生成反馈 JSON</button>
          <button className="btn btn-warning btn-sm" disabled={t.training || !t.feedbackStats?.exportPath} onClick={() => t.triggerRetrain()}>{t.training ? "训练中..." : "重训模型"}</button>
        </div>
      </div>

      {/* Historical training card */}
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold">历史数据训练</h3>
              <p className="text-xs text-base-content/50 mt-1">用历史学期课表数据训练 LightGBM 单模型，不进数据库；请只放训练集课表，测试集不要放进来。</p>
            </div>
            <div className="flex gap-2">
              <input type="text" id="history-raw-dir" className="input input-bordered input-sm w-80 font-mono text-xs" placeholder={HISTORY_TRAINING_DIR} defaultValue={HISTORY_TRAINING_DIR} />
              <button className="btn btn-primary btn-sm" disabled={t.historyTraining} onClick={() => {
                const dir = (document.getElementById("history-raw-dir") as HTMLInputElement)?.value;
                t.trainFromHistory(dir || HISTORY_TRAINING_DIR);
              }}>{t.historyTraining ? "训练中..." : "开始历史训练"}</button>
            </div>
          </div>
          {(t.historyTraining || t.historyTrainingLogs.length > 0) && (
            <div className="mt-3 rounded-lg bg-neutral text-neutral-content p-3">
              <div className="mb-2 flex items-center justify-between text-xs font-medium">
                <span>实时训练日志</span>
                {t.historyTraining && <span className="loading loading-spinner loading-xs" />}
              </div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{t.historyTrainingLogs.join("\n") || "等待训练日志..."}</pre>
            </div>
          )}
          {t.historyTrainResult && t.historyTrainResult?.status !== "RUNNING" && (
            <div className={`mt-3 text-xs p-3 rounded-lg ${t.historyTrainResult?.status === "ok" ? "bg-success/10 text-success" : "bg-error/10 text-error"}`}>
              <div className="font-medium mb-1">{t.historyTrainResult?.status === "ok" ? "训练完成" : "训练失败"}</div>
              <div className="opacity-70 font-mono whitespace-pre-wrap max-h-32 overflow-auto">{JSON.stringify(t.historyTrainResult, null, 2)}</div>
            </div>
          )}
        </div>
      </div>

      {/* Historical dataset browser */}
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="font-semibold">历史训练样本</h3>
              <p className="text-xs text-base-content/50 mt-1">查看已清洗的历史课表训练数据，主表只展示 accepted，待复核样本单独查看。</p>
            </div>
            <button className="btn btn-ghost btn-sm" disabled={t.datasetLoading} onClick={() => t.loadHistoryDataset()}>
              {t.datasetLoading ? <span className="loading loading-spinner loading-xs" /> : "刷新样本"}
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 mt-4">
            <div>
              <label className="label py-1 text-xs">质量</label>
              <select className="select select-bordered select-sm w-full" value={t.datasetQuality} onChange={e => t.updateDatasetFilter({ quality: e.target.value })}>
                <option value="accepted">训练集</option>
                <option value="review_needed">待复核</option>
              </select>
            </div>
            <div>
              <label className="label py-1 text-xs">表</label>
              <select className="select select-bordered select-sm w-full" value={t.datasetTable} onChange={e => t.updateDatasetFilter({ table: e.target.value })}>
                {DATASET_TABLES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </div>
            <div className="xl:col-span-2">
              <label className="label py-1 text-xs">关键词</label>
              <input className="input input-bordered input-sm w-full" value={t.datasetKeyword} onChange={e => t.setDatasetKeyword?.(e.target.value)} onKeyDown={e => { if (e.key === "Enter") t.updateDatasetFilter({ keyword: t.datasetKeyword }); }} placeholder="课程、教师、班级、教室" />
            </div>
            <div>
              <label className="label py-1 text-xs">学期</label>
              <select className="select select-bordered select-sm w-full" value={t.datasetSemester} onChange={e => t.updateDatasetFilter({ semester: e.target.value })}>
                <option value="">全部</option>
                {t.dataset?.semesters?.map(sem => <option key={sem} value={sem}>{sem}</option>)}
              </select>
            </div>
            <div>
              <label className="label py-1 text-xs">课时下限</label>
              <input className="input input-bordered input-sm w-full" type="number" min="0" value={t.datasetMinHours} onChange={e => t.updateDatasetFilter({ minHours: e.target.value })} />
            </div>
            <div>
              <label className="label py-1 text-xs">课时上限</label>
              <input className="input input-bordered input-sm w-full" type="number" min="0" value={t.datasetMaxHours} onChange={e => t.updateDatasetFilter({ maxHours: e.target.value })} />
            </div>
            <div>
              <label className="label py-1 text-xs">排序</label>
              <div className="join w-full">
                <select className="select select-bordered select-sm join-item flex-1 min-w-0" value={t.datasetSortBy} onChange={e => t.updateDatasetFilter({ sortBy: e.target.value })}>
                  {(t.dataset?.sortOptions || []).map(option => <option key={option} value={option}>{fieldLabel(option)}</option>)}
                </select>
                <button className="btn btn-sm join-item" onClick={() => t.updateDatasetFilter({ sortDir: t.datasetSortDir === "desc" ? "asc" : "desc" })}>{t.datasetSortDir === "desc" ? "降" : "升"}</button>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mt-4">
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">筛选样本</div><div className="stat-value text-lg">{t.dataset?.total || 0}</div></div>
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">原始行数</div><div className="stat-value text-lg">{t.dataset?.rawTotal || 0}</div></div>
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">课程数</div><div className="stat-value text-lg">{t.dataset?.summary?.courseCount ?? "-"}</div></div>
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">教师数</div><div className="stat-value text-lg">{t.dataset?.summary?.teacherCount ?? "-"}</div></div>
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">班级数</div><div className="stat-value text-lg">{t.dataset?.summary?.classCount ?? "-"}</div></div>
            <div className="stat bg-base-200 rounded-lg p-3"><div className="stat-title text-xs">课时合计</div><div className="stat-value text-lg">{t.dataset?.summary?.hourTotal ?? "-"}</div></div>
          </div>

          <div className="overflow-x-auto mt-4">
            <table className="table table-sm table-zebra">
              <thead><tr>{datasetColumns.map(col => <th key={col}>{fieldLabel(col)}</th>)}</tr></thead>
              <tbody>
                {t.datasetLoading ? <tr><td colSpan={datasetColumns.length || 1} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
                : !t.dataset?.rows?.length ? <tr><td colSpan={datasetColumns.length || 1} className="text-center py-8 text-base-content/40">没有匹配的训练样本</td></tr>
                : t.dataset.rows.map((row, index) => (
                  <tr key={index}>
                    {datasetColumns.map(col => {
                      const value = displayCell(row, col);
                      return <td key={col} className={["source_schedule", "raw_source", "course_name", "class_name"].includes(col) ? "max-w-[240px] truncate" : ""} title={String(value ?? "")}>{compactValue(value)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-xs text-base-content/50">
            <span>{t.dataset?.path || "历史训练集尚未加载"}</span>
            <div className="join">
              <button className="btn btn-xs join-item" disabled={t.datasetPage <= 1 || t.datasetLoading} onClick={() => t.updateDatasetFilter({ page: t.datasetPage - 1 })}>上一页</button>
              <button className="btn btn-xs join-item btn-ghost">第 {t.datasetPage} / {totalPages} 页</button>
              <button className="btn btn-xs join-item" disabled={t.datasetPage >= totalPages || t.datasetLoading} onClick={() => t.updateDatasetFilter({ page: t.datasetPage + 1 })}>下一页</button>
            </div>
          </div>
        </div>
      </div>

      {/* Training alert */}
      {t.trainResult && (
        <div className={`alert ${t.trainResult.status === "SUCCEEDED" ? "alert-success" : t.trainResult.status === "FAILED" ? "alert-error" : "alert-warning"}`}>
          <span>{t.trainResult.status === "SUCCEEDED" ? `训练完成 · ${(t.trainResult as any).sampleCount || 0} 条样本已生成` : t.trainResult.status === "FAILED" ? `训练失败: ${(t.trainResult as any).message}` : `训练中: ${(t.trainResult as any).message}`}</span>
        </div>
      )}

      {/* Stats cards */}
      {t.lastLog ? (
        <div className="grid grid-cols-6 gap-3">
          <StatCard label="模型版本" value={t.lastLog.modelVersion || "-"} />
          <StatCard label="训练类型" value={t.typeLabel(t.lastLog.trainingType)} />
          <StatCard label="样本总数" value={t.lastLog.sampleCount || 0} />
          <StatCard label="正样本率" value={t.positiveRate + "%"} />
          <StatCard label="AUC" value={t.lastLog.evalAuc != null ? t.lastLog.evalAuc.toFixed(4) : "-"} />
          <StatCard label="评分分离度" value={t.lastLog.evalAccuracy != null ? t.lastLog.evalAccuracy.toFixed(4) : "-"} />
        </div>
      ) : !t.training ? (
        <div className="text-center py-12 text-base-content/40">还没有训练记录，请先创建排课任务并生成方案，积累反馈数据后再开始重训</div>
      ) : null}

      {/* Event ledger */}
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body p-4">
          <div className="flex items-center gap-2 font-bold mb-3"><span>反馈事件采集台账</span><span className="badge badge-ghost badge-xs ml-auto">确认/调整/人工标注自动采集</span></div>
          <div className="grid grid-cols-4 gap-3 mb-3">
            {t.eventCards.map(c => <div key={c.label} className="text-center p-3 bg-base-200 rounded-lg"><div className="text-xl font-bold">{c.value}</div><div className="text-xs text-base-content/50">{c.label}</div></div>)}
          </div>
          <div className="overflow-x-auto">
            <table className="table table-xs"><thead><tr><th>事件类型</th><th>事件数</th></tr></thead><tbody>{t.eventSummary?.eventTypes?.map((et, i) => <tr key={i}><td>{t.eventLabel(et.eventType)}</td><td className="text-center">{et.eventCount}</td></tr>)}</tbody></table>
            <table className="table table-xs mt-3"><thead><tr><th>事件ID</th><th>任务</th><th>行为类型</th><th>方案</th><th>片段</th><th>教学任务</th><th>原因码</th><th>说明</th><th>时间</th></tr></thead><tbody>{t.eventSummary?.recentEvents?.map((ev: any, i) => <tr key={i}><td>{ev.id}</td><td>{ev.taskId}</td><td>{t.eventLabel(ev.eventType)}</td><td>{ev.schemeId}</td><td>{ev.itemId}</td><td>{ev.teachingTaskId}</td><td className="max-w-[100px] truncate">{ev.reasonCode}</td><td className="max-w-[150px] truncate">{ev.reasonText}</td><td>{t.fmtTime(ev.createdAt)}</td></tr>)}</tbody></table>
          </div>
          <p className="text-xs text-base-content/40 mt-3">当前阶段先沉淀原始反馈事件，不直接把未选候选当负样本。后续样本构造器会按优先级和移动相消规则把事件转成训练样本。</p>
        </div>
      </div>

      {/* Feedback data + Sample composition */}
      <div className="grid grid-cols-7 gap-4">
        <div className="col-span-4 card bg-base-100 shadow-sm">
          <div className="card-body p-4">
            <div className="flex items-center gap-2 font-bold mb-3"><span>可用于训练的数据</span>{t.feedbackStats && <span className="badge badge-ghost badge-xs ml-auto">{t.feedbackStats.exportPath ? "已导出" : "待导出"}</span>}</div>
            {t.feedbackStats ? (
              <div className="grid grid-cols-6 gap-2 text-center">
                <div><div className="font-bold">{t.feedbackStats.schemeCount}</div><div className="text-xs text-base-content/50">候选方案</div></div>
                <div><div className="font-bold">{t.feedbackStats.itemCount}</div><div className="text-xs text-base-content/50">排课明细</div></div>
                <div><div className="font-bold text-success">{t.feedbackStats.feedbackCount}</div><div className="text-xs text-base-content/50">确认反馈</div></div>
                <div><div className="font-bold text-warning">{t.feedbackStats.adjustmentCount}</div><div className="text-xs text-base-content/50">人工调整</div></div>
                <div><div className="font-bold text-error">{t.feedbackStats.conflictCount}</div><div className="text-xs text-base-content/50">冲突记录</div></div>
                <div><div className="font-bold text-info">{t.feedbackStats.eventCount || 0}</div><div className="text-xs text-base-content/50">反馈事件</div></div>
              </div>
            ) : <div className="text-center py-8 text-base-content/40">点击"生成反馈 JSON"后查看本次导出的反馈数据统计</div>}
            <div className="divider my-2" />
            <p className="text-xs text-base-content/40"><strong>标签策略：</strong>先记录方案确认、片段移动和人工标注事件；真正的正负样本由后续样本构造器统一生成，避免把未选候选误判成负样本。</p>
          </div>
        </div>
        <div className="col-span-3 card bg-base-100 shadow-sm">
          <div className="card-body p-4 text-center">
            <div className="font-bold mb-3">训练样本构成</div>
            {t.lastLog ? <>
              <div className="text-5xl font-bold">{t.lastLog.sampleCount || 0}</div>
              <div className="text-sm text-base-content/50 mb-4">最近训练样本总数</div>
              <div className="flex gap-3 justify-center"><span className="badge badge-success">{t.lastLog.positiveCount || 0} 正样本</span><span className="badge badge-error">{t.lastLog.negativeCount || 0} 负样本</span></div>
              <div className="mt-4"><div className="h-2 rounded bg-base-200 overflow-hidden"><div className="h-full rounded bg-gradient-to-r from-success to-info transition-all" style={{ width: t.positiveRate + "%" }} /></div><div className="flex justify-between text-xs text-base-content/40 mt-1"><span>正 {t.positiveRate}%</span><span>负 {100 - t.positiveRate}%</span></div></div>
            </> : <div className="text-center py-8 text-base-content/40">暂无训练数据</div>}
          </div>
        </div>
      </div>

      {/* Training logs */}
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body p-4">
          <div className="font-bold mb-3">训练历史</div>
          <div className="overflow-x-auto">
            <table className="table table-sm table-zebra"><thead><tr><th>版本</th><th>类型</th><th>样本数</th><th>AUC</th><th>准确率</th><th>状态</th><th>创建时间</th></tr></thead><tbody>
              {t.logsLoading ? <tr><td colSpan={7} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
              : t.trainingLogs.length === 0 ? <tr><td colSpan={7} className="text-center py-8 text-base-content/40">暂无训练记录</td></tr>
              : t.trainingLogs.map(log => <tr key={log.id}><td>{log.modelVersion || "-"}</td><td>{t.typeLabel(log.trainingType)}</td><td>{log.sampleCount}</td><td>{log.evalAuc?.toFixed(4) || "-"}</td><td>{log.evalAccuracy?.toFixed(4) || "-"}</td><td><span className={`badge badge-xs ${log.status === "SUCCEEDED" ? "badge-success" : log.status === "FAILED" ? "badge-error" : "badge-warning"}`}>{log.status === "SUCCEEDED" ? "成功" : log.status === "FAILED" ? "失败" : "运行中"}</span></td><td>{t.fmtTime(log.createdAt)}</td></tr>)}
            </tbody></table>
          </div>
        </div>
      </div>
    </div>
  );
}
