import type { TeachingTask } from "../hooks/useTeachingTasks";

interface Course { id: number; name: string; code: string; courseType: string; }
interface Teacher { id: number; name: string; }
interface ClassGroup { id: number; name: string; }
interface Classroom { id: number; name: string; building: string; capacity: number; }

interface Props {
  form: TeachingTask; onChange: (f: TeachingTask) => void;
  saving: boolean; onSave: () => void; onClose: () => void;
  courses: Course[]; teachers: Teacher[]; classGroups: ClassGroup[]; classrooms: Classroom[];
  onCourseChanged: (id: number) => void; onCourseTypeChanged: (type: string) => void;
}

export default function TeachingTaskDialog({ form, onChange, saving, onSave, onClose, courses, teachers, classGroups, classrooms, onCourseChanged, onCourseTypeChanged }: Props) {
  return (
    <div className="modal modal-open">
      <div className="modal-box max-w-lg">
        <h3 className="font-bold text-lg mb-4">{form.id ? "编辑教学任务" : "新增教学任务"}</h3>
        <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
          <div>
            <label className="label pb-1"><span className="label-text">课程</span></label>
            <select className="select select-bordered w-full" value={form.courseId || ""} onChange={e => onCourseChanged(Number(e.target.value))}>
              <option value="">请选择课程</option>
              {courses.map(c => <option key={c.id} value={c.id}>{c.name} ({c.code || ""})</option>)}
            </select>
          </div>
          <div>
            <label className="label pb-1"><span className="label-text">课程类型</span></label>
            <select className="select select-bordered w-full" value={form.courseType} onChange={e => onCourseTypeChanged(e.target.value)}>
              <option value="理论课">理论课</option><option value="上机课">上机课</option><option value="实践课">实践课</option>
            </select>
          </div>
          <div><label className="label pb-1"><span className="label-text">所需教室</span></label><input className="input input-bordered w-full" value={form.requiredRoomType} disabled /></div>
          <div><label className="label pb-1"><span className="label-text">任务批次</span></label><input className="input input-bordered w-full" placeholder="如 2026学期上 / 测试用例01" value={form.taskBatch || "DEFAULT"} onChange={e => onChange({...form, taskBatch: e.target.value})} /></div>
          <div>
            <label className="label pb-1"><span className="label-text">主讲教师</span></label>
            <select className="select select-bordered w-full" value={form.primaryTeacherId || ""} onChange={e => onChange({...form, primaryTeacherId: Number(e.target.value)})}>
              <option value="">请选择主讲教师</option>
              {teachers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label pb-1"><span className="label-text">协作教师</span></label>
            <select className="select select-bordered w-full" value={form.assistantTeacherId || ""} onChange={e => onChange({...form, assistantTeacherId: e.target.value ? Number(e.target.value) : undefined})}>
              <option value="">可选</option>
              {teachers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div><label className="label pb-1"><span className="label-text">总课时</span></label><input type="number" className="input input-bordered w-full" value={form.totalHours} min={2} step={2} onChange={e => onChange({...form, totalHours: Number(e.target.value)})} /><span className="text-xs text-base-content/40 mt-1">必须是2的倍数</span></div>
          <div><label className="label pb-1"><span className="label-text">每周次数（可选）</span></label><input type="number" className="input input-bordered w-full" value={form.sessionsPerWeek ?? ""} min={1} placeholder="不填由系统推算" onChange={e => onChange({...form, sessionsPerWeek: e.target.value === "" ? "" : Number(e.target.value)})} /></div>
          <div><label className="label pb-1"><span className="label-text">持续周数（可选）</span></label><input type="number" className="input input-bordered w-full" value={form.durationWeeks ?? ""} min={1} placeholder="不填由系统推算" onChange={e => onChange({...form, durationWeeks: e.target.value === "" ? "" : Number(e.target.value)})} /><span className="text-xs text-base-content/40 mt-1">次数×周数×每次课时须等于总课时</span></div>
          <div>
            <label className="label pb-1"><span className="label-text">推荐教室</span></label>
            <select className="select select-bordered w-full" value={form.classroomId || ""} onChange={e => onChange({...form, classroomId: e.target.value ? Number(e.target.value) : undefined})}>
              <option value="">可选，不选由排课自动分配</option>
              {classrooms.map(cr => <option key={cr.id} value={cr.id}>{cr.name}({cr.building || "?"}, {cr.capacity}座)</option>)}
            </select>
          </div>
          <div>
            <label className="label pb-1"><span className="label-text">班级</span></label>
            <div className="flex flex-wrap gap-1 border border-base-300 rounded-lg p-2 min-h-[40px]">
              {classGroups.map(cg => {
                const selected = form.classGroupIds.includes(cg.id);
                return (
                  <button key={cg.id} type="button"
                    className={`badge badge-sm cursor-pointer ${selected ? "badge-primary" : "badge-ghost"}`}
                    onClick={() => onChange({...form, classGroupIds: selected ? form.classGroupIds.filter(id => id !== cg.id) : [...form.classGroupIds, cg.id]})}
                  >{cg.name}</button>
                );
              })}
            </div>
          </div>
          <div><label className="label pb-1"><span className="label-text">备注</span></label><textarea className="textarea textarea-bordered w-full" rows={2} value={form.notes || ""} onChange={e => onChange({...form, notes: e.target.value})} /></div>
          <div>
            <label className="label pb-1"><span className="label-text">状态</span></label>
            <select className="select select-bordered w-full" value={form.status} onChange={e => onChange({...form, status: e.target.value})}>
              <option value="ACTIVE">启用</option><option value="INACTIVE">停用</option>
            </select>
          </div>
        </div>
        <div className="modal-action">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>取消</button>
          <button className="btn btn-primary btn-sm" disabled={saving} onClick={onSave}>{saving ? <span className="loading loading-spinner loading-xs" /> : "保存"}</button>
        </div>
      </div>
    </div>
  );
}
