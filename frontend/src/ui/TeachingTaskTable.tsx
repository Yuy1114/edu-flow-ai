import type { TeachingTask } from "../hooks/useTeachingTasks";
import BatchActionBar from "./BatchActionBar";

interface Props {
  tasks: TeachingTask[]; loading: boolean; search: string; onSearchChange: (v: string) => void;
  courseTypeFilter: string; onCourseTypeFilterChange: (v: string) => void;
  taskBatchFilter: string; taskBatchOptions: string[]; onTaskBatchFilterChange: (v: string) => void;
  statusFilter: string; onStatusFilterChange: (v: string) => void;
  page: number; pageSize: number; total: number;
  onPageChange: (v: number) => void; onPageSizeChange: (v: number) => void;
  deleting: number | null; onEdit: (row: TeachingTask) => void; onDelete: (id: number) => void; onAdd: () => void;
  batch: any;
}

export default function TeachingTaskTable({ tasks, loading, search, onSearchChange, courseTypeFilter, onCourseTypeFilterChange, taskBatchFilter, taskBatchOptions, onTaskBatchFilterChange, statusFilter, onStatusFilterChange, page, pageSize, total, onPageChange, onPageSizeChange, deleting, onEdit, onDelete, onAdd, batch }: Props) {
  function onClear() { onSearchChange(""); onCourseTypeFilterChange(""); onTaskBatchFilterChange(""); onStatusFilterChange(""); }
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasFilter = search || courseTypeFilter || taskBatchFilter || statusFilter;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <button className="btn btn-primary btn-sm" onClick={onAdd}>新增教学任务</button>
        <select className="select select-bordered select-sm w-28" value={statusFilter} onChange={e => onStatusFilterChange(e.target.value)}>
          <option value="">全部状态</option><option value="ACTIVE">启用</option><option value="INACTIVE">停用</option>
        </select>
        <select className="select select-bordered select-sm w-28" value={courseTypeFilter} onChange={e => onCourseTypeFilterChange(e.target.value)}>
          <option value="">课程类型</option><option value="理论课">理论课</option><option value="上机课">上机课</option><option value="实验课">实验课</option><option value="实践课">实践课</option>
        </select>
        <select className="select select-bordered select-sm w-36" value={taskBatchFilter} onChange={e => onTaskBatchFilterChange(e.target.value)}>
          <option value="">任务批次</option>
          {taskBatchOptions.map(batch => <option key={batch} value={batch}>{batch}</option>)}
        </select>
        <input type="text" placeholder="搜索课程/教师/班级..." className="input input-bordered input-sm w-56" value={search} onChange={e => onSearchChange(e.target.value)} onKeyDown={e => e.key === "Enter" && onSearchChange(search)} />
        {hasFilter && <button className="btn btn-ghost btn-sm" onClick={onClear}>清空</button>}
      </div>
      <BatchActionBar label="教学任务" selectedCount={batch.selectedCount} filteredCount={total} busy={batch.batchBusy} onSelectFiltered={batch.selectFiltered} onClearSelection={batch.clearSelection} onDisable={batch.batchDisable} onDelete={batch.batchDelete} />
      <div className="overflow-x-auto">
        <table className="table table-zebra table-sm">
          <thead><tr><th><input type="checkbox" className="checkbox checkbox-xs" checked={batch.pageSelected} onChange={batch.togglePageSelected} title={batch.pageIndeterminate ? "当前页已部分选择" : "选择当前页"} /></th><th>ID</th><th>批次</th><th>课程</th><th>主讲教师</th><th>协作教师</th><th>类型</th><th>总课时</th><th>教室</th><th>班级</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={12} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
            : tasks.length === 0 ? <tr><td colSpan={12} className="text-center py-8 text-base-content/40">暂无教学任务</td></tr>
            : tasks.map(t => (
              <tr key={t.id}>
                <td><input type="checkbox" className="checkbox checkbox-xs" checked={t.id !== null && batch.selectedIds.includes(t.id)} onChange={() => t.id !== null && batch.toggleSelected(t.id)} /></td>
                <td>{t.id}</td>
                <td><span className="badge badge-xs badge-outline">{t.taskBatch || "DEFAULT"}</span></td>
                <td className="max-w-[120px] truncate">{t.course?.name || "-"}</td>
                <td className="max-w-[80px] truncate">{t.primaryTeacher?.name || "-"}</td>
                <td className="max-w-[80px] truncate">{t.assistantTeacher?.name || "-"}</td>
                <td>
                  <span className={`badge badge-xs ${t.course?.courseType === "理论课" ? "badge-primary" : t.course?.courseType === "上机课" ? "badge-success" : "badge-warning"}`}>
                    {t.course?.courseType || "-"}
                  </span>
                </td>
                <td>{t.totalHours}</td>
                <td className="max-w-[100px] truncate">{t.classroom ? `${t.classroom.name}(${t.classroom.capacity}座)` : "-"}</td>
                <td className="max-w-[100px] truncate">{t.classGroups?.map(cg => cg.name).join(", ") || "-"}</td>
                <td><span className={`badge badge-xs ${t.status === "ACTIVE" ? "badge-success" : "badge-ghost"}`}>{t.status === "ACTIVE" ? "启用" : "停用"}</span></td>
                <td><div className="flex gap-1">
                  <button className="btn btn-xs btn-ghost" onClick={() => onEdit(t)}>编辑</button>
                  <button className="btn btn-xs btn-ghost text-error" disabled={deleting === t.id} onClick={() => t.id !== null && onDelete(t.id)}>
                    {deleting === t.id ? <span className="loading loading-spinner loading-xs" /> : "删除"}
                  </button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between mt-4">
        <div className="flex items-center gap-2 text-sm text-base-content/60"><span>共 {total} 条</span><select className="select select-bordered select-xs w-20" value={pageSize} onChange={e => onPageSizeChange(Number(e.target.value))}><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select><span>条/页</span></div>
        <div className="join">
          <button className="join-item btn btn-xs" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
          <span className="join-item btn btn-xs no-animation">{page} / {totalPages}</span>
          <button className="join-item btn btn-xs" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一页</button>
        </div>
      </div>
    </div>
  );
}
