import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import request from "../api/request";
import { toast } from "sonner";
import {
  ConflictDetails,
  filterSchemeItems,
  SchemeItemsTable,
  SchemeTimetable,
  uniqueOptions,
} from "../components/SchemeDetailView";
import type { AllocationScheme, SchemeItem, TemplateDraftView } from "../hooks/useAllocation";
import { ALL_PERIODS } from "../lib/schedulingTime";

type ClassroomOption = { id: number; name: string; capacity: number; classroomType: string; status: string };
type FragmentForm = {
  mode: "create" | "edit";
  fragmentId?: number;
  templateId: number;
  teachingTaskId: number;
  classroomId: number;
  dayOfWeek: number;
  periodIndex: number;
  consecutiveSlots: number;
  durationWeeks: number;
  weekNumbers: number[];
  reason: string;
};

export default function AllocationSchemeDetailPage() {
  const { schemeId } = useParams({ from: "/admin/allocation/schemes/$schemeId" });
  const [scheme, setScheme] = useState<AllocationScheme | null>(null);
  const [items, setItems] = useState<SchemeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedConflictId, setSelectedConflictId] = useState<number | null>(null);
  const [teacher, setTeacher] = useState("");
  const [classGroup, setClassGroup] = useState("");
  const [classroom, setClassroom] = useState("");
  const [keyword, setKeyword] = useState("");
  const [draft, setDraft] = useState<TemplateDraftView | null>(null);
  const [classrooms, setClassrooms] = useState<ClassroomOption[]>([]);
  const [fragmentForm, setFragmentForm] = useState<FragmentForm | null>(null);
  const [savingFragment, setSavingFragment] = useState(false);

  async function loadDetail() {
    setLoading(true);
    try {
      const schemeData = await request.get<AllocationScheme>(`/api/allocation-schemes/${schemeId}`);
      const v35 = schemeData.modelVersion?.startsWith("v3.5") === true;
      const [itemData, draftData, classroomData] = await Promise.all([
        request.get<SchemeItem[]>(`/api/allocation-schemes/${schemeId}/items`),
        v35 ? request.get<TemplateDraftView>(`/api/allocation-schemes/${schemeId}/template-draft`) : Promise.resolve(null),
        v35 ? request.get<ClassroomOption[]>("/api/classrooms", { params: { status: "ACTIVE" } }) : Promise.resolve([]),
      ]);
      setScheme(schemeData);
      setItems(Array.isArray(itemData) ? itemData : []);
      setDraft(draftData);
      setClassrooms(Array.isArray(classroomData) ? classroomData : []);
    } catch {
      setScheme(null);
      setItems([]);
      setDraft(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadDetail(); }, [schemeId]);

  const teacherOptions = useMemo(() => uniqueOptions(items, "teacherName"), [items]);
  const classOptions = useMemo(() => uniqueOptions(items, "classGroupName"), [items]);
  const classroomOptions = useMemo(() => uniqueOptions(items, "classroomName"), [items]);
  const filteredItems = useMemo(
    () => filterSchemeItems(items, { teacher, classGroup, classroom, keyword }),
    [items, teacher, classGroup, classroom, keyword],
  );
  const conflictCount = filteredItems.filter(item => item.valid === false).length;
  const hasFilter = teacher || classGroup || classroom || keyword;
  const isV35 = scheme?.modelVersion?.startsWith("v3.5") === true;
  const editableDraft = isV35 && scheme?.status === "CANDIDATE";

  function openCreateFragment() {
    if (!draft || draft.templates.length === 0 || classrooms.length === 0) return;
    const task = draft.audit.taskHours.find(row => row.status === "UNDER") ?? draft.audit.taskHours[0];
    if (!task) return;
    const template = draft.templates[0];
    const missing = Math.max(1, -task.deltaHours);
    const defaultSpan = task.sessionPeriods || 2;
    const span = missing % defaultSpan === 0 ? defaultSpan : 1;
    const durationWeeks = Math.min(template.weekNumbers.length, Math.max(1, Math.ceil(missing / span)));
    setFragmentForm({
      mode: "create",
      templateId: template.id,
      teachingTaskId: task.teachingTaskId,
      classroomId: classrooms[0].id,
      dayOfWeek: 1,
      periodIndex: span === 4 ? 1 : 1,
      consecutiveSlots: span,
      durationWeeks,
      weekNumbers: template.weekNumbers.slice(0, durationWeeks),
      reason: "补齐未达标课时",
    });
  }

  function openEditFragment(item: SchemeItem) {
    if (!editableDraft || !item.templateFragmentId || !item.templateId) return;
    const mappedWeeks = draft?.templates.find(template => template.id === item.templateId)?.weekNumbers.length || 1;
    setFragmentForm({
      mode: "edit",
      fragmentId: item.templateFragmentId,
      templateId: item.templateId,
      teachingTaskId: item.teachingTaskId,
      classroomId: item.classroomId,
      dayOfWeek: item.dayOfWeek,
      periodIndex: item.periodIndex,
      consecutiveSlots: item.consecutiveSlots || 1,
      durationWeeks: Math.min(item.durationWeeks || 1, mappedWeeks),
      weekNumbers: item.weekNumbers?.length
        ? item.weekNumbers
        : (draft?.templates.find(template => template.id === item.templateId)?.weekNumbers || []).slice(0, Math.min(item.durationWeeks || 1, mappedWeeks)),
      reason: "人工调整模板片段",
    });
  }

  async function saveFragment() {
    if (!fragmentForm) return;
    setSavingFragment(true);
    try {
      const endpoint = `/api/allocation-schemes/${schemeId}/template-fragments`;
      if (fragmentForm.mode === "create") await request.post(endpoint, fragmentForm);
      else await request.put(`${endpoint}/${fragmentForm.fragmentId}`, fragmentForm);
      toast.success(fragmentForm.mode === "create" ? "模板片段已新增并重新审计" : "模板片段已调整并重新审计");
      setFragmentForm(null);
      await loadDetail();
    } finally {
      setSavingFragment(false);
    }
  }

  async function deleteFragment(item: SchemeItem) {
    if (!item.templateFragmentId || !confirm(`确认删除「${item.courseName}」模板片段？它在该模板覆盖周内的所有安排都会删除。`)) return;
    await request.delete(`/api/allocation-schemes/${schemeId}/template-fragments/${item.templateFragmentId}`, { params: { reason: "人工删除模板片段" } });
    toast.success("模板片段已删除并重新审计");
    await loadDetail();
  }

  async function confirmDraft() {
    if (!draft?.audit.valid) return;
    await request.post(`/api/allocation-schemes/${schemeId}/confirm`);
    toast.success("模板方案已确认并发布为正式课表");
    await loadDetail();
  }

  async function acceptManualReview() {
    if (!draft || draft.audit.hardConflictCount > 0) return;
    const reason = window.prompt("当前演示环境未接权限认证，操作人会记录为本地演示操作员。请填写接受未排任务、非规则pattern或课时尾差的处理原因：");
    if (!reason?.trim()) return;
    await request.post(`/api/allocation-schemes/${schemeId}/manual-review-acceptance`, {
      reason: reason.trim(),
    });
    toast.success("人工复核项已接受并留档；系统已重新执行全部硬约束审计");
    await loadDetail();
  }

  const stats = {
    totalItems: items.length,
    conflicts: items.filter(i => i.valid === false).length,
    conflictRate: items.length ? (items.filter(i => i.valid === false).length / items.length * 100).toFixed(1) : "0",
    courses: new Set(items.map(i => i.courseName)).size,
    // teacherName/classGroupName are display strings that may contain several
    // stable identities (assistant teachers and combined classes). Count the
    // already-split filter options so the summary does not report one combined
    // class or a primary+assistant pair as a single resource.
    teachers: teacherOptions.length,
    classes: classOptions.length,
    weeks: new Set(items.map(i => i.weekNumber)).size,
  };
  const selectedDraftTemplate = draft?.templates.find(template => template.id === fragmentForm?.templateId);
  const selectedAuditTask = draft?.audit.taskHours.find(task => task.teachingTaskId === fragmentForm?.teachingTaskId);
  const auditComplete = draft?.audit.reviewStatus?.startsWith("COMPLETE") === true;
  const canAcceptManualReview = editableDraft
    && draft?.audit.reviewStatus === "NEEDS_MANUAL_REVIEW"
    && draft.audit.hardConflictCount === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-base-content/50 mb-1">
            <Link to="/admin/allocation" className="link link-hover">分课任务</Link>
            <span>/</span>
            <span>方案详情</span>
          </div>
          <h2 className="break-words text-xl font-semibold tracking-tight">{scheme?.schemeName || scheme?.name || `方案 #${schemeId}`}</h2>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            {scheme?.schemeScore != null && <span className="badge badge-outline badge-info font-mono">评分 {scheme.schemeScore.toFixed(4)}</span>}
            {scheme?.status && <span className="badge badge-outline">{scheme.status}</span>}
            <span className="badge badge-ghost">{filteredItems.length} / {items.length} 条记录</span>
            {conflictCount > 0 && <span className="badge badge-error">{conflictCount} 个冲突</span>}
          </div>
        </div>
		<div className="flex flex-wrap gap-2">
		  {editableDraft && <button className="btn btn-sm btn-primary" onClick={openCreateFragment} disabled={!draft?.templates.length || !classrooms.length}>新增模板片段</button>}
		  {canAcceptManualReview && <button className="btn btn-sm btn-warning" onClick={acceptManualReview}>接受人工复核项</button>}
		  {isV35 && scheme?.status !== "CONFIRMED" && <button className="btn btn-sm btn-success" onClick={confirmDraft} disabled={!draft?.audit.valid}>确认并发布</button>}
		  <Link to="/admin/allocation" className="btn btn-sm btn-ghost">返回方案列表</Link>
		</div>
      </div>

	  {isV35 && draft && (
		<div className={`border p-4 ${auditComplete ? "border-success/40 bg-success/5" : draft.audit.reviewStatus === "BLOCKED" ? "border-error/40 bg-error/5" : "border-warning/40 bg-warning/5"}`}>
		  <div className="flex flex-wrap items-center justify-between gap-2">
			<div>
			  <div className="font-semibold">模板草案审计：{draft.audit.reviewStatus === "COMPLETE_WITH_EXCEPTION" ? "人工复核项已接受，可确认发布" : draft.audit.reviewStatus === "COMPLETE" ? "已通过，可确认发布" : draft.audit.reviewStatus === "BLOCKED" ? "存在不可豁免的硬约束错误" : "存在待教务确认的未排任务、pattern警告或课时尾差"}</div>
			  <div className="mt-1 text-xs text-base-content/60">批次 {draft.generationRunId} · {draft.templates.length} 张动态模板 · 课时 {draft.audit.scheduledTotalHours}/{draft.audit.requiredTotalHours}</div>
			</div>
			<div className="flex flex-wrap gap-2 text-xs">
			  <span className="badge badge-outline">硬问题 {draft.audit.hardConflictCount}</span>
			  <span className="badge badge-outline">课时异常任务 {draft.audit.hourMismatchTaskCount}</span>
			  <span className="badge badge-outline">课时差 {draft.audit.deltaTotalHours > 0 ? "+" : ""}{draft.audit.deltaTotalHours}</span>
			</div>
		  </div>
		  {draft.audit.taskHours.some(row => row.status !== "OK") && <div className="mt-3 flex max-h-28 flex-wrap gap-1 overflow-y-auto">{draft.audit.taskHours.filter(row => row.status !== "OK").map(row => <span key={row.teachingTaskId} className="badge badge-sm badge-warning badge-outline">{row.courseName} #{row.teachingTaskId}: {row.scheduledHours}/{row.requiredHours}</span>)}</div>}
		  {draft.audit.issues.length > 0 && <details className="mt-3"><summary className="cursor-pointer text-xs font-medium">查看审计问题（{draft.audit.issues.length}）</summary><ul className="mt-2 max-h-36 list-disc overflow-y-auto pl-5 text-xs text-base-content/70">{draft.audit.issues.slice(0, 100).map((issue, index) => <li key={`${index}-${issue}`}>{issue}</li>)}</ul></details>}
		</div>
	  )}

      {/* Quality metrics */}
      {!loading && items.length > 0 && (
        <div className="flex flex-wrap items-stretch gap-3">
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[100px] flex-1">
            <div className="stat-title text-xs text-base-content/60">已排记录</div>
            <div className="stat-value text-lg text-primary">{stats.totalItems}</div>
            <div className="stat-desc text-[10px] text-base-content/40">{stats.weeks} 周 · {stats.courses} 门课程</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[100px] flex-1">
            <div className="stat-title text-xs text-base-content/60">冲突</div>
            <div className={`stat-value text-lg ${stats.conflicts > 0 ? "text-error" : "text-success"}`}>
              {stats.conflicts}
              <span className="text-sm font-normal ml-1 text-base-content/40">({stats.conflictRate}%)</span>
            </div>
            <div className="stat-desc text-[10px] text-base-content/40">{stats.conflicts > 0 ? "需要人工处理" : "无冲突"}</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[100px] flex-1">
            <div className="stat-title text-xs text-base-content/60">教师</div>
            <div className="stat-value text-lg text-info">{stats.teachers}</div>
            <div className="stat-desc text-[10px] text-base-content/40">涉及教师数</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[100px] flex-1">
            <div className="stat-title text-xs text-base-content/60">班级</div>
            <div className="stat-value text-lg text-accent">{stats.classes}</div>
            <div className="stat-desc text-[10px] text-base-content/40">覆盖班级数</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[100px] flex-1">
            <div className="stat-title text-xs text-base-content/60">冲突率</div>
            <div className={`stat-value text-lg ${stats.conflicts > 0 ? "text-warning" : "text-success"}`}>{stats.conflictRate}%</div>
            <div className="stat-desc text-[10px] text-base-content/40">{stats.conflicts > 0 ? `${stats.conflicts} / ${stats.totalItems}` : "全量通过"}</div>
          </div>
        </div>
      )}

      <div className="card bg-base-100 shadow-sm border border-base-300">
        <div className="card-body p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
            <label className="form-control">
              <div className="label py-1"><span className="label-text text-xs text-base-content/60">关键词</span></div>
              <input className="input input-sm input-bordered" placeholder="课程 / 教师 / 班级 / 教室" value={keyword} onChange={event => setKeyword(event.target.value)} />
            </label>
            <label className="form-control">
              <div className="label py-1"><span className="label-text text-xs text-base-content/60">教师</span></div>
              <select className="select select-sm select-bordered" value={teacher} onChange={event => setTeacher(event.target.value)}>
                <option value="">全部教师</option>
                {teacherOptions.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
            <label className="form-control">
              <div className="label py-1"><span className="label-text text-xs text-base-content/60">班级</span></div>
              <select className="select select-sm select-bordered" value={classGroup} onChange={event => setClassGroup(event.target.value)}>
                <option value="">全部班级</option>
                {classOptions.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
            <label className="form-control">
              <div className="label py-1"><span className="label-text text-xs text-base-content/60">教室</span></div>
              <select className="select select-sm select-bordered" value={classroom} onChange={event => setClassroom(event.target.value)}>
                <option value="">全部教室</option>
                {classroomOptions.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
            <div className="flex items-end">
              <button className="btn btn-sm btn-outline w-full" disabled={!hasFilter} onClick={() => { setTeacher(""); setClassGroup(""); setClassroom(""); setKeyword(""); }}>
                清空筛选
              </button>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24"><span className="loading loading-spinner loading-lg text-primary" /></div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center py-24 text-base-content/30 font-medium">暂无排课明细数据</div>
      ) : filteredItems.length === 0 ? (
        <div className="flex items-center justify-center py-24 text-base-content/30 font-medium">没有匹配当前筛选条件的记录</div>
      ) : (
        <div className="space-y-5">
		  <SchemeTimetable items={filteredItems} selectedConflictId={selectedConflictId} onConflictClick={item => setSelectedConflictId(selectedConflictId === item.id ? null : item.id)} editable={editableDraft} onItemClick={openEditFragment} />
          <details className="collapse collapse-arrow border border-base-300 rounded-lg bg-base-100">
            <summary className="collapse-title text-sm font-medium text-base-content/70">列表视图（{filteredItems.length} 条）</summary>
			<div className="collapse-content p-0"><SchemeItemsTable items={filteredItems} editable={editableDraft} onEdit={openEditFragment} onDelete={deleteFragment} /></div>
          </details>
          <ConflictDetails items={filteredItems} selectedConflictId={selectedConflictId} onSelect={setSelectedConflictId} />
        </div>
      )}

	  {fragmentForm && draft && (
		<div className="modal modal-open">
		  <div className="modal-box max-h-[90vh] w-[calc(100%-1rem)] max-w-2xl overflow-y-auto p-4 sm:p-6">
			<h3 className="text-lg font-bold">{fragmentForm.mode === "create" ? "新增模板片段" : "调整模板片段"}</h3>
			<p className="mt-1 text-xs text-base-content/55">可精确选择任意一个或多个模板映射周，并使用周末、晚间或单个45分钟节次人工补排；保存后立即重做全部硬约束和课时审计。</p>
			<div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
			  <label className="form-control"><span className="label-text mb-1 text-xs">动态模板</span><select className="select select-sm select-bordered" disabled={fragmentForm.mode === "edit"} value={fragmentForm.templateId} onChange={event => { const templateId = Number(event.target.value); const weeks = draft.templates.find(template => template.id === templateId)?.weekNumbers || []; setFragmentForm({ ...fragmentForm, templateId, durationWeeks: weeks.length ? 1 : 0, weekNumbers: weeks.slice(0, 1) }); }}>{draft.templates.map((template, index) => <option key={template.id} value={template.id}>模板{index + 1} · {template.templateCode}（{template.weekNumbers.join(",")}周）</option>)}</select></label>
			  <label className="form-control"><span className="label-text mb-1 text-xs">教学任务</span><select className="select select-sm select-bordered" disabled={fragmentForm.mode === "edit"} value={fragmentForm.teachingTaskId} onChange={event => { const teachingTaskId = Number(event.target.value); const task = draft.audit.taskHours.find(row => row.teachingTaskId === teachingTaskId); setFragmentForm({ ...fragmentForm, teachingTaskId, consecutiveSlots: task?.sessionPeriods || 2 }); }}>{draft.audit.taskHours.map(task => <option key={task.teachingTaskId} value={task.teachingTaskId}>{task.courseName} #{task.teachingTaskId} · {task.scheduledHours}/{task.requiredHours}{task.status !== "OK" ? "（需调整）" : ""}</option>)}</select></label>
			  <label className="form-control"><span className="label-text mb-1 text-xs">教室</span><select className="select select-sm select-bordered" value={fragmentForm.classroomId} onChange={event => setFragmentForm({ ...fragmentForm, classroomId: Number(event.target.value) })}>{classrooms.map(room => <option key={room.id} value={room.id}>{room.name} · {room.classroomType} · {room.capacity}人</option>)}</select></label>
			  <label className="form-control"><span className="label-text mb-1 text-xs">星期</span><select className="select select-sm select-bordered" value={fragmentForm.dayOfWeek} onChange={event => setFragmentForm({ ...fragmentForm, dayOfWeek: Number(event.target.value) })}>{[1,2,3,4,5,6,7].map(day => <option key={day} value={day}>{["","周一","周二","周三","周四","周五","周六","周日"][day]}</option>)}</select></label>
			  <label className="form-control"><span className="label-text mb-1 text-xs">起始节次</span><select className="select select-sm select-bordered" value={fragmentForm.periodIndex} onChange={event => setFragmentForm({ ...fragmentForm, periodIndex: Number(event.target.value) })}>{ALL_PERIODS.filter(period => fragmentForm.consecutiveSlots === 1 || (fragmentForm.consecutiveSlots === 2 ? [1,3,5,7,9].includes(period) : [1,5].includes(period))).map(period => <option key={period} value={period}>第{period}节</option>)}</select></label>
			  <label className="form-control"><span className="label-text mb-1 text-xs">连续节数</span><select className="select select-sm select-bordered" disabled={fragmentForm.mode === "edit"} value={fragmentForm.consecutiveSlots} onChange={event => setFragmentForm({ ...fragmentForm, consecutiveSlots: Number(event.target.value), periodIndex: 1 })}><option value={selectedAuditTask?.sessionPeriods || 2}>课程默认 {selectedAuditTask?.sessionPeriods || 2} 节</option><option value={1}>人工补 1 节</option></select></label>
			  <fieldset className="md:col-span-2"><legend className="mb-1 text-xs">精确生效周次（已选 {fragmentForm.weekNumbers.length} 周）</legend><div className="flex max-h-28 flex-wrap gap-2 overflow-y-auto rounded-lg border border-base-300 p-2">{(selectedDraftTemplate?.weekNumbers || []).map(week => { const checked = fragmentForm.weekNumbers.includes(week); return <label key={week} className={`flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs ${checked ? "bg-primary/15 text-primary" : "bg-base-200"}`}><input type="checkbox" className="checkbox checkbox-xs" checked={checked} onChange={() => { const weekNumbers = checked ? fragmentForm.weekNumbers.filter(value => value !== week) : [...fragmentForm.weekNumbers, week].sort((a, b) => a - b); setFragmentForm({ ...fragmentForm, weekNumbers, durationWeeks: weekNumbers.length }); }} />第{week}周</label>; })}</div></fieldset>
			  <label className="form-control"><span className="label-text mb-1 text-xs">调整原因</span><input className="input input-sm input-bordered" value={fragmentForm.reason} onChange={event => setFragmentForm({ ...fragmentForm, reason: event.target.value })} /></label>
			</div>
			<div className="modal-action"><button className="btn btn-sm btn-ghost" onClick={() => setFragmentForm(null)}>取消</button><button className="btn btn-sm btn-primary" disabled={savingFragment || fragmentForm.weekNumbers.length === 0} onClick={saveFragment}>{savingFragment ? <span className="loading loading-spinner loading-xs" /> : "保存并重审计"}</button></div>
		  </div>
		</div>
	  )}
    </div>
  );
}
