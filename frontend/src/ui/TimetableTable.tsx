import type { Assignment } from "../hooks/useTimetable";

interface Props { assignments: Assignment[]; loading: boolean; }

export default function TimetableTable({ assignments, loading }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="table table-zebra table-sm">
        <thead><tr><th>ID</th><th>课程</th><th>班级</th><th>教师</th><th>教室</th><th>时间段</th><th>周次</th><th>星期</th><th>节次</th><th>状态</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={10} className="text-center py-8"><span className="loading loading-spinner" /></td></tr>
          : assignments.length === 0 ? <tr><td colSpan={10} className="text-center py-8 text-base-content/40">暂无排课数据</td></tr>
          : assignments.map(a => (
            <tr key={a.id}>
              <td>{a.id}</td><td>{a.courseName}</td><td>{a.classGroupName}</td><td>{a.teacherName}</td><td>{a.classroomName}</td>
              <td>{a.timeSlotLabel}</td><td>{a.weekNumber}</td><td>{a.dayOfWeek}</td><td>{a.periodIndex}{(a.consecutiveSlots || 1) > 1 ? `–${a.periodIndex + (a.consecutiveSlots || 1) - 1}` : ""}</td>
              <td><span className={`badge badge-xs ${a.status === "ACTIVE" ? "badge-success" : "badge-ghost"}`}>{a.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
