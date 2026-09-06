import { EXPORT_ROLES, useTimetable } from "../hooks/useTimetable";
import TimetableTable from "../ui/TimetableTable";
import TimetableGrid from "../ui/TimetableGrid";

export default function TimetableManager() {
  const t = useTimetable();

  return (
    <div>
      {/* Filters */}
      <div className="card bg-base-100 shadow-sm mb-4">
        <div className="card-body p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div><label className="label pb-1 text-xs">排课任务</label><select className="select select-bordered select-sm min-w-44" value={t.filters.allocationTaskId} onChange={e => t.setFilters({...t.filters, allocationTaskId: e.target.value})}><option value="">全部排课任务</option>{t.allocationTasks.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">教师</label><select className="select select-bordered select-sm min-w-36" value={t.filters.teacherId} onChange={e => t.setFilters({...t.filters, teacherId: e.target.value})}><option value="">全部教师</option>{t.teachers.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">班级</label><select className="select select-bordered select-sm min-w-40" value={t.filters.classGroupId} onChange={e => t.setFilters({...t.filters, classGroupId: e.target.value})}><option value="">全部班级</option>{t.classGroups.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">课程</label><select className="select select-bordered select-sm min-w-44" value={t.filters.courseId} onChange={e => t.setFilters({...t.filters, courseId: e.target.value})}><option value="">全部课程</option>{t.courses.map(row => <option key={row.id} value={row.id}>{row.name}{row.code ? ` (${row.code})` : ""}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">教室</label><select className="select select-bordered select-sm min-w-36" value={t.filters.classroomId} onChange={e => t.setFilters({...t.filters, classroomId: e.target.value})}><option value="">全部教室</option>{t.classrooms.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">周次</label><select className="select select-bordered select-sm w-24" value={t.filters.weekNumber} onChange={e => t.setFilters({...t.filters, weekNumber: e.target.value})}><option value="">全部</option>{Array.from({length: 18}, (_, index) => index + 1).map(week => <option key={week} value={week}>第{week}周</option>)}</select></div>
            <div><label className="label pb-1 text-xs">星期</label><select className="select select-bordered select-sm w-24" value={t.filters.dayOfWeek} onChange={e => t.setFilters({...t.filters, dayOfWeek: e.target.value})}><option value="">全部</option>{t.dayNames.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}</select></div>
            <div><label className="label pb-1 text-xs">状态</label><select className="select select-bordered select-sm w-28" value={t.filters.status} onChange={e => t.setFilters({...t.filters, status: e.target.value})}><option value="ACTIVE">生效中</option><option value="">全部状态</option><option value="INACTIVE">已失效</option></select></div>
            <button className="btn btn-primary btn-sm" onClick={() => t.loadAssignments()}>查询</button>
            <button className="btn btn-ghost btn-sm" onClick={t.resetFilters}>重置</button>
          </div>
        </div>
      </div>

      {t.hourAudit && (
        <div className={`mb-4 border p-4 ${t.hourAudit.mismatchTaskCount > 0 ? "border-warning/40 bg-warning/5" : "border-success/40 bg-success/5"}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="font-semibold">正式课表课时终审：{t.hourAudit.mismatchTaskCount > 0 ? `${t.hourAudit.mismatchTaskCount} 个教学任务需人工微调` : "全部教学任务课时吻合"}</div>
              <div className="mt-1 text-xs text-base-content/60">已排 {t.hourAudit.scheduledTotalHours} / 应排 {t.hourAudit.requiredTotalHours} 个45分钟原子课时，差值 {t.hourAudit.deltaTotalHours > 0 ? "+" : ""}{t.hourAudit.deltaTotalHours}</div>
            </div>
            <span className={`badge ${t.hourAudit.mismatchTaskCount > 0 ? "badge-warning" : "badge-success"}`}>课时异常 {t.hourAudit.mismatchTaskCount}</span>
          </div>
          {t.hourAudit.mismatchTaskCount > 0 && <details className="mt-2"><summary className="cursor-pointer text-xs font-medium">查看少排/超排任务</summary><div className="mt-2 flex max-h-28 flex-wrap gap-1 overflow-y-auto">{t.hourAudit.tasks.filter(row => row.status !== "OK").map(row => <span key={row.teachingTaskId} className="badge badge-sm badge-warning badge-outline">{row.courseName} #{row.teachingTaskId}: {row.scheduledHours}/{row.requiredHours}（{row.deltaHours > 0 ? "+" : ""}{row.deltaHours}）</span>)}</div></details>}
        </div>
      )}

      {/* View toggle + 多角色导出 */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="join">
          <button className={`join-item btn btn-sm ${t.viewMode === "table" ? "btn-active" : ""}`} onClick={() => t.setViewMode("table")}>表格视图</button>
          <button className={`join-item btn btn-sm ${t.viewMode === "grid" ? "btn-active" : ""}`} onClick={() => t.setViewMode("grid")}>课程表视图</button>
        </div>
        <span className="text-sm text-base-content/50">共 {t.assignments.length} 条记录</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className="text-xs text-base-content/50">按当前筛选条件导出 Excel</span>
          {EXPORT_ROLES.map(role => (
            <button key={role.value} className="btn btn-outline btn-sm"
              disabled={t.exporting !== null}
              onClick={() => void t.exportTimetable(role.value)}>
              {t.exporting === role.value && <span className="loading loading-spinner loading-xs" />}
              {role.label}
            </button>
          ))}
        </div>
      </div>

      {t.viewMode === "table" && <TimetableTable assignments={t.assignments} loading={t.loading} />}
      {t.viewMode === "grid" && (
        <TimetableGrid loading={t.loading} currentWeek={t.currentWeek} allWeeks={t.allWeeks}
          weekItems={t.weekItems} dayNames={t.dayNames} itemsAtSlot={t.itemsAtSlot} onWeekChange={t.setCurrentWeek} />
      )}
    </div>
  );
}
