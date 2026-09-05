import type { Course } from "../hooks/useCourses";

interface CourseDialogProps {
  form: Course;
  onChange: (form: Course) => void;
  saving: boolean;
  onSave: () => void;
  onClose: () => void;
}

export default function CourseDialog({
  form,
  onChange,
  saving,
  onSave,
  onClose,
}: CourseDialogProps) {
  return (
    <div className="modal modal-open">
      <div className="modal-box max-w-md">
        <h3 className="font-bold text-lg mb-4">
          {form.id ? "编辑课程" : "新增课程"}
        </h3>
        <div className="space-y-3">
          <div>
            <label className="label pb-1">
              <span className="label-text">课程名称</span>
            </label>
            <input
              className="input input-bordered w-full"
              value={form.name}
              onChange={(e) => onChange({ ...form, name: e.target.value })}
            />
          </div>
          <div>
            <label className="label pb-1">
              <span className="label-text">课程代码</span>
            </label>
            <input
              className="input input-bordered w-full"
              value={form.code}
              onChange={(e) => onChange({ ...form, code: e.target.value })}
            />
          </div>
          <div>
            <label className="label pb-1">
              <span className="label-text">课程类型</span>
            </label>
            <select
              className="select select-bordered w-full"
              value={form.courseType}
              onChange={(e) => onChange({ ...form, courseType: e.target.value })}
            >
              <option value="">选择类型</option>
              <option value="理论课">理论课</option>
              <option value="上机课">上机课</option>
              <option value="实验课">实验课</option>
              <option value="实践课">实践课</option>
            </select>
          </div>
          <div>
            <label className="label pb-1">
              <span className="label-text">教室类型</span>
            </label>
            <select
              className="select select-bordered w-full"
              value={form.requiredRoomType}
              onChange={(e) =>
                onChange({ ...form, requiredRoomType: e.target.value })
              }
            >
              <option value="">选择教室类型</option>
              <option value="普通教室">普通教室</option>
              <option value="机房">机房</option>
              <option value="阶梯教室">阶梯教室</option>
              <option value="操场">操场</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label pb-1">
                <span className="label-text">学分</span>
              </label>
              <input
                type="number"
                className="input input-bordered w-full"
                value={form.credits}
                min={0}
                onChange={(e) =>
                  onChange({ ...form, credits: Number(e.target.value) })
                }
              />
            </div>
            <div>
              <label className="label pb-1">
                <span className="label-text">学时</span>
              </label>
              <input
                type="number"
                className="input input-bordered w-full"
                value={form.requiredHours}
                min={1}
                onChange={(e) =>
                  onChange({ ...form, requiredHours: Number(e.target.value) })
                }
              />
            </div>
          </div>
          <div>
            <label className="label pb-1">
              <span className="label-text">描述</span>
            </label>
            <textarea
              className="textarea textarea-bordered w-full"
              rows={2}
              value={form.description || ""}
              onChange={(e) =>
                onChange({ ...form, description: e.target.value })
              }
            />
          </div>
          <div>
            <label className="label pb-1">
              <span className="label-text">状态</span>
            </label>
            <select
              className="select select-bordered w-full"
              value={form.status}
              onChange={(e) => onChange({ ...form, status: e.target.value })}
            >
              <option value="ACTIVE">启用</option>
              <option value="INACTIVE">停用</option>
            </select>
          </div>
        </div>
        <div className="modal-action">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            取消
          </button>
          <button
            className="btn btn-primary btn-sm"
            disabled={saving}
            onClick={onSave}
          >
            {saving ? (
              <span className="loading loading-spinner loading-xs" />
            ) : (
              "保存"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
