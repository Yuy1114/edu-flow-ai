import { Link } from "@tanstack/react-router";
import { useAllocation } from "../hooks/useAllocation";
import { AUTO_SCHEDULING_PERIODS, parsePeriodSelection, periodSegment } from "../lib/schedulingTime";

export default function AllocationManager() {
  const a = useAllocation();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2>分课任务</h2>
        <button className="btn btn-primary btn-sm" onClick={() => a.openTaskDialog()}>新增排课任务</button>
      </div>

      {/* Tasks table */}
      <div className="overflow-x-auto">
        <table className="table table-zebra table-sm">
          <thead><tr><th>ID</th><th>任务名称</th><th>方案数</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {a.loading ? <tr><td colSpan={5} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
            : a.tasks.length === 0 ? <tr><td colSpan={5} className="text-center py-8 text-base-content/40">暂无排课任务</td></tr>
            : a.tasks.map(t => <tr key={t.id} className={a.selectedTask?.id === t.id ? "bg-primary/5" : ""}>
                <td>{t.id}</td>
                <td className="font-medium cursor-pointer hover:text-primary" onClick={() => a.selectTask(t)}>{t.name || `任务 #${t.id}`}</td>
                <td>{t.schemeCount ?? "-"}</td>
                <td><span className={`badge badge-xs ${t.status === "RUNNING" ? "badge-info" : t.status === "CONFIRMED" || t.status === "GENERATED" ? "badge-success" : t.status === "BLOCKED" || t.status === "FAILED" ? "badge-error" : t.status === "NEEDS_MANUAL_REVIEW" ? "badge-warning" : "badge-ghost"}`}>{t.status}</span></td>
                <td><div className="flex flex-wrap gap-1">
                  <button className="btn btn-xs btn-ghost" onClick={() => a.openTaskDialog(t)}>编辑</button>
                  <button className="btn btn-xs btn-ghost text-error" onClick={() => a.deleteTask(t.id)}>删除</button>
                </div></td>
              </tr>)}
          </tbody>
        </table>
      </div>

      {/* Selected task -> schemes + detail */}
      {a.selectedTask && (
        <div className="flex flex-col gap-4">
          {/* Schemes section */}
          <div className="card bg-base-100 shadow-sm">
            <div className="card-body p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0 break-words font-bold">方案列表 — {a.selectedTask.name || `任务 #${a.selectedTask.id}`}</span>
                <button className="btn btn-info btn-sm" disabled={a.generating || !a.selectedTask} onClick={a.generateSchemes}>
                  {a.generating ? <><span className="loading loading-spinner loading-xs" /> V3.5 排课中...</> : "V3.5 模板排课"}
                </button>
              </div>
              {a.generating && (
                <div className="mb-4">
                  <div className="flex items-center justify-between text-xs text-base-content/60 mb-1">
                    <span>{a.generateStatus}</span>
                    <span>{a.generateProgress}%</span>
                  </div>
                  <div className="h-2.5 rounded-full bg-base-300 overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-warning to-success transition-all duration-500" style={{ width: `${a.generateProgress}%` }} />
                  </div>
                </div>
              )}
              {!a.generating && (a.generationError || a.lastGeneration && a.lastGeneration.status !== "IDLE") && (
                <div className={`mb-4 rounded-lg border p-3 text-sm ${a.generationError ? "border-error/40 bg-error/5" : a.lastGeneration?.status === "NEEDS_MANUAL_REVIEW" ? "border-warning/40 bg-warning/5" : "border-success/40 bg-success/5"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`badge badge-sm ${a.generationError ? "badge-error" : a.lastGeneration?.status === "NEEDS_MANUAL_REVIEW" ? "badge-warning" : "badge-success"}`}>{a.lastGeneration?.status || "FAILED"}</span>
                    <span className="font-medium">{a.generateStatus || "已恢复持久排课作业状态"}</span>
                    {a.lastGeneration?.jobId && <span className="break-all font-mono text-[10px] text-base-content/45">作业 {a.lastGeneration.jobId}</span>}
                    <button className="btn btn-ghost btn-xs ml-auto" onClick={a.refreshGenerationStatus}>刷新状态</button>
                  </div>
                  {a.generationError && <div className="mt-2 whitespace-pre-wrap break-words text-xs text-error">{a.generationError}</div>}
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="table table-sm table-zebra">
                  <thead><tr><th>ID</th><th>方案名</th><th>评分</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
                  <tbody>
                    {a.schemesLoading ? <tr><td colSpan={6} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
                    : a.schemes.length === 0 ? <tr><td colSpan={6} className="text-center py-8 text-base-content/40">暂无方案，点击「生成排课方案」开始</td></tr>
                    : a.schemes.map(s => <tr key={s.id}>
                        <td>{s.id}</td>
						<td>{s.schemeName || s.name || `方案 #${s.id}`}</td>
                        <td>{s.schemeScore != null ? s.schemeScore.toFixed(2) : "-"}</td>
                        <td><span className={`badge badge-xs ${s.status === "CONFIRMED" ? "badge-success" : s.status === "GENERATED" ? "badge-info" : "badge-warning"}`}>{s.status}</span></td>
                        <td>{s.createdAt?.replace("T"," ").substring(0,19) || "-"}</td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            <Link to="/admin/allocation/schemes/$schemeId" params={{ schemeId: String(s.id) }} className="btn btn-xs btn-ghost">查看详情</Link>
							<button className="btn btn-xs btn-success" disabled={s.status === "CONFIRMED" || s.valid === false} onClick={() => a.confirmScheme(s.id)}>确认方案</button>
                          </div>
                        </td>
                      </tr>)}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

      {/* V3.5 Template section */}
      {a.selectedTask && a.v35Templates.length > 0 && (
        <div className="card bg-base-100 shadow-sm border border-info/20">
          <div className="card-body p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="font-bold text-info">V3.5 模板排课结果</span>
              <button className="btn btn-ghost btn-xs" onClick={() => a.loadV35Templates(a.selectedTask!.id)}>刷新</button>
            </div>

            {/* Template list */}
            <div className="flex flex-wrap gap-2 mb-3">
              {a.v35Templates.map((t: any) => (
                <div key={t.templateCode} className="badge badge-info badge-outline gap-1 p-3">
                  <span className="font-mono text-xs">{t.templateCode}</span>
                  <span className="text-[10px] opacity-60">{t.fragmentCount} 片段 · {t.taskCount} 任务</span>
                </div>
              ))}
            </div>

            {/* Week -> template mapping */}
            <details className="collapse collapse-arrow border border-base-300 rounded-lg">
              <summary className="collapse-title text-sm font-medium text-base-content/70 min-h-0 py-2">
                周模板映射（{a.v35TemplateWeeks.length} 周）
              </summary>
              <div className="collapse-content p-0">
                <div className="flex flex-wrap gap-1.5 p-2">
                  {a.v35TemplateWeeks.map((w: any) => (
                    <button
                      key={w.weekNumber}
					  className={`btn btn-xs ${a.v35SelectedWeek === w.weekNumber ? "btn-info" : "btn-ghost"}`}
                      onClick={() => a.loadV35WeekTimetable(a.selectedTask!.id, w.weekNumber)}
					  title={w.templateCode}
                    >
                      第{w.weekNumber}周
					  <span className="text-[9px] opacity-50 ml-0.5">
						模板{Math.max(1, a.v35Templates.findIndex((template: any) => template.id === w.templateId) + 1)}
					  </span>
                    </button>
                  ))}
                </div>
              </div>
            </details>

            {/* Week timetable */}
            {a.v35SelectedWeek && a.v35WeekTimetable.length > 0 && (
              <div className="mt-3 overflow-x-auto max-h-64 overflow-y-auto">
                <table className="table table-xs table-zebra">
                  <thead>
                    <tr>
                      <th>周</th>
                      <th>星期</th>
                      <th>课段</th>
                      <th>教室</th>
                      <th>班级</th>
                      <th>课程</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.v35WeekTimetable.slice(0, 100).map((e: any, i: number) => (
                      <tr key={i}>
                        <td>{e.weekNumber}</td>
                        <td>{["","周一","周二","周三","周四","周五","周六","周日"][e.dayOfWeek] || e.dayOfWeek}</td>
                        <td>{e.periodIndex}</td>
                        <td className="font-mono text-xs">{e.classroomName}</td>
                        <td className="max-w-[120px] truncate">{e.className}</td>
                        <td className="max-w-[150px] truncate">{e.courseName}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {a.v35WeekTimetable.length > 100 && (
                  <div className="text-center text-xs text-base-content/40 py-2">
                    仅显示前 100 条，共 {a.v35WeekTimetable.length} 条
                  </div>
                )}
              </div>
            )}
            {a.v35SelectedWeek && a.v35WeekTimetable.length === 0 && (
              <div className="text-center text-xs text-base-content/40 py-4">该周暂无课表数据</div>
            )}
          </div>
        </div>
      )}
        </div>
      )}

      {/* Task dialog */}
      {a.taskDialog && (
        <div className="modal modal-open">
          <div className="modal-box max-h-[85vh] w-[calc(100%-1rem)] max-w-2xl overflow-y-auto p-4 sm:p-6">
            <h3 className="font-bold text-lg mb-4">{a.taskForm.id ? "编辑排课任务" : "新增排课任务"}</h3>
            <div className="space-y-3">
              <div><label className="label pb-1"><span className="label-text">任务名称</span></label><input className="input input-bordered w-full" value={a.taskForm.name} onChange={e => a.setTaskForm({...a.taskForm, name: e.target.value})} /></div>

              {/* Generation config */}
              <details className="collapse collapse-arrow border border-base-300 rounded-lg">
                <summary className="collapse-title text-sm font-medium text-base-content/70 min-h-0 py-2">排课配置</summary>
                <div className="collapse-content px-2 py-0">
                  <div className="space-y-3 pt-2">
                    <div>
                      <label className="label py-1"><span className="label-text text-xs">可用星期</span></label>
                      <div className="flex flex-wrap gap-1">
                        {["周一","周二","周三","周四","周五","周六","周日"].map((label, i) => {
                          const day = i + 1;
                          const cfg = a.taskForm.generationConfig || {};
                          const days: number[] = typeof cfg.allowedWeekdays === "string" ? cfg.allowedWeekdays.split(",").map(Number) : (cfg.allowedWeekdays || [1,2,3,4,5]);
                          const selected = days.includes(day);
                          return (
                            <button key={day} type="button"
                              className={`badge badge-sm cursor-pointer ${selected ? "badge-primary" : "badge-ghost"}`}
                              onClick={() => {
                                const newDays = selected ? days.filter(d => d !== day) : [...days, day].sort();
                                a.updateConfig("allowedWeekdays", newDays);
                              }}
                            >{label}</button>
                          );
                        })}
                      </div>
                    </div>
                    <div>
                      <label className="label py-1">
                        <span className="label-text text-xs">自动排课可用节次</span>
                        <span className="label-text-alt text-[10px] text-base-content/45">每节45分钟；默认上午1-4、下午5-8</span>
                      </label>
                      <div className="flex flex-wrap gap-1">
                        {a.PERIODS.map(period => {
                          const cfg = a.taskForm.generationConfig || {};
                          const periods = parsePeriodSelection(cfg.allowedPeriods);
                          const selected = periods.includes(period);
                          return (
                            <button key={period} type="button"
                              className={`badge badge-sm cursor-pointer ${selected ? "badge-primary" : "badge-ghost"} ${period > 8 ? "border-warning/50" : ""}`}
                              onClick={() => {
                                const newPeriods = selected ? periods.filter(p => p !== period) : [...periods, period].sort();
                                a.updateConfig("allowedPeriods", newPeriods);
                              }}
                              title={period > 8 ? "晚间保留节次，自动排课默认不启用，人工调课仍可使用" : `${periodSegment(period)}自动排课节次`}
                            >第{period}节{period > 8 ? " · 晚" : ""}</button>
                          );
                        })}
                      </div>
                      <p className="mt-1 text-[10px] text-base-content/45">
                        理论课通常连续2节，上机/实验课连续4节；第9-10节和周末默认留给人工调课。
                        {!AUTO_SCHEDULING_PERIODS.every(period => parsePeriodSelection(a.taskForm.generationConfig?.allowedPeriods).includes(period)) && " 当前已自定义白天时段。"}
                      </p>
                    </div>
                    <div>
                      <label className="label py-1"><span className="label-text text-xs">可用周次</span></label>
                      <div className="flex flex-wrap gap-1">
                        {Array.from({length: 18}, (_, i) => i + 1).map(week => {
                          const cfg = a.taskForm.generationConfig || {};
                          const weeks: number[] = typeof cfg.allowedWeeks === "string" ? cfg.allowedWeeks.split(",").map(Number) : (cfg.allowedWeeks || Array.from({length: 18}, (_, i) => i + 1));
                          const selected = weeks.includes(week);
                          return (
                            <button key={week} type="button"
                              className={`btn btn-xs min-w-7 ${selected ? "btn-primary" : "btn-ghost"}`}
                              onClick={() => {
                                const newWeeks = selected ? weeks.filter(w => w !== week) : [...weeks, week].sort((a,b) => a-b);
                                a.updateConfig("allowedWeeks", newWeeks);
                              }}
                            >{week}</button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              </details>

              {/* Teaching task selector */}
              <div>
                <label className="label pb-1"><span className="label-text">绑定教学任务</span></label>
                <div className="flex items-center justify-between mb-2 flex-wrap gap-1">
                  <span className="text-xs text-base-content/40">共 {a.filteredTeachingTasks.length} / {a.teachingTasks.length} 项，已选 {a.taskForm.teachingTaskIds.length} 项</span>
                  <div className="flex items-center gap-2">
                    <select className="select select-ghost select-xs w-28" value={a.teachingTaskBatchFilter} onChange={e => a.setTeachingTaskBatchFilter(e.target.value)}>
                      <option value="">全部批次</option>
                      {a.teachingTaskBatchOptions.map(b => <option key={b} value={b}>{b}</option>)}
                    </select>
                    <button className="btn btn-ghost btn-xs" onClick={() => a.selectAllTeachingTasks(true)}>全选</button>
                    <button className="btn btn-ghost btn-xs" onClick={() => a.selectAllTeachingTasks(false)}>取消</button>
                  </div>
                </div>
                <div className="border border-base-300 rounded-lg max-h-48 overflow-y-auto p-1">
                  {a.teachingTasksLoading ? (
                    <div className="text-center py-4"><span className="loading loading-spinner loading-xs" /></div>
                  ) : a.filteredTeachingTasks.length === 0 ? (
                    <div className="text-center py-4 text-base-content/40 text-xs">暂无匹配教学任务</div>
                  ) : (
                    <div className="space-y-0.5">
                      {a.filteredTeachingTasks.map(tt => {
                        const selected = a.taskForm.teachingTaskIds.includes(tt.id);
                        return (
                          <label key={tt.id} className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-xs hover:bg-base-200 ${selected ? "bg-primary/10" : ""}`}>
                            <input type="checkbox" className="checkbox checkbox-xs" checked={selected} onChange={() => a.toggleTeachingTask(tt.id)} />
                            <span className="font-medium">{tt.courseName}</span>
                            <span className="text-base-content/40">{tt.teacherName}</span>
                            <span className="text-base-content/30 text-[10px] ml-auto truncate max-w-[120px]">{tt.classGroupNames}</span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>

            </div>
            <div className="modal-action">
              <button className="btn btn-ghost btn-sm" onClick={() => a.setTaskDialog(false)}>取消</button>
              <button className="btn btn-primary btn-sm" disabled={a.saving} onClick={a.saveTask}>{a.saving ? <span className="loading loading-spinner loading-xs" /> : "保存"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
