import { useMemo, useState } from "react";
import type { SchemeItem } from "../hooks/useAllocation";
import { ALL_PERIODS, periodDetailLabel } from "../lib/schedulingTime";

const RAINBOW_HUES = [0, 20, 45, 80, 140, 175, 200, 230, 260, 290, 320, 345];
// Domain values are ISO-style 1=Monday ... 7=Sunday. Keep index zero empty so
// Sunday is not rendered as the raw number 7.
const DAY_LABELS = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];

function taskKey(item: SchemeItem) {
  return `${item.courseName ?? ""}|${item.teacherName ?? ""}|${item.classGroupName ?? ""}`;
}

function buildHueMap(items: SchemeItem[]) {
  const keys = [...new Set(items.map(taskKey))].sort();
  const hueMap = new Map<string, number>();
  keys.forEach((key, index) => hueMap.set(key, RAINBOW_HUES[index % RAINBOW_HUES.length]));
  return hueMap;
}

export function uniqueOptions(items: SchemeItem[], key: keyof SchemeItem) {
  const multiValue = key === "teacherName" || key === "classGroupName";
  return [...new Set(items.flatMap(item => {
    const value = String(item[key] ?? "").trim();
    return multiValue ? value.split(/[、,，]/).map(part => part.trim()).filter(Boolean) : value ? [value] : [];
  }))].sort();
}

export function filterSchemeItems(
  items: SchemeItem[],
  filters: { teacher?: string; classGroup?: string; classroom?: string; keyword?: string },
) {
  const keyword = filters.keyword?.trim().toLowerCase();
  return items.filter(item => {
    if (filters.teacher && !String(item.teacherName ?? "").split(/[、,，]/).map(value => value.trim()).includes(filters.teacher)) return false;
    if (filters.classGroup && !String(item.classGroupName ?? "").split(/[、,，]/).map(value => value.trim()).includes(filters.classGroup)) return false;
    if (filters.classroom && item.classroomName !== filters.classroom) return false;
    if (!keyword) return true;
    return [item.courseName, item.teacherName, item.classGroupName, item.classroomName]
      .some(value => String(value ?? "").toLowerCase().includes(keyword));
  });
}

export function occupiedPeriods(item: Pick<SchemeItem, "periodIndex" | "consecutiveSlots">) {
  const start = Number(item.periodIndex);
  const span = Math.max(1, Number(item.consecutiveSlots) || 1);
  return Array.from({ length: span }, (_, offset) => start + offset)
    .filter(period => ALL_PERIODS.includes(period));
}

export function periodRangeLabel(item: Pick<SchemeItem, "periodIndex" | "consecutiveSlots">) {
  const periods = occupiedPeriods(item);
  if (periods.length <= 1) return `第${periods[0] ?? item.periodIndex}节`;
  return `第${periods[0]}–${periods[periods.length - 1]}节`;
}

export function SchemeTimetable({
  items,
  selectedConflictId,
  onConflictClick,
	editable = false,
	onItemClick,
}: {
  items: SchemeItem[];
  selectedConflictId?: number | null;
  onConflictClick?: (item: SchemeItem) => void;
	editable?: boolean;
	onItemClick?: (item: SchemeItem) => void;
}) {
  const [week, setWeek] = useState(0);
  const allWeeks = [...new Set(items.map(item => item.weekNumber))].sort((a, b) => a - b);
  const currentWeek = week && allWeeks.includes(week) ? week : allWeeks[0] || 0;
  const weekItems = items.filter(item => item.weekNumber === currentWeek);
  const hueMap = useMemo(() => buildHueMap(items), [items]);

  const days = [1, 2, 3, 4, 5, 6, 7];
  const periods = ALL_PERIODS;
  const slotMap = new Map<string, Array<{ item: SchemeItem; occupiedPeriod: number; start: boolean }>>();
  for (const item of weekItems) {
    for (const occupiedPeriod of occupiedPeriods(item)) {
      const key = `${item.dayOfWeek}-${occupiedPeriod}`;
      if (!slotMap.has(key)) slotMap.set(key, []);
      slotMap.get(key)!.push({ item, occupiedPeriod, start: occupiedPeriod === item.periodIndex });
    }
  }

  return (
    <div>
      {allWeeks.length > 1 && (
        <div className="flex items-center gap-2 mb-3 overflow-x-auto pb-1">
          <span className="text-xs text-base-content/40 font-medium shrink-0">周次</span>
          <div className="join">
            {allWeeks.map(weekNumber => (
              <button
                key={weekNumber}
                className={`join-item btn btn-xs min-w-8 ${weekNumber === currentWeek ? "btn-active btn-primary text-primary-content" : "btn-ghost text-base-content/60"}`}
                onClick={() => setWeek(weekNumber)}
              >
                {weekNumber}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-100">
        <table className="table table-sm w-full table-fixed min-w-[72rem] xl:min-w-0">
          <thead>
            <tr className="bg-base-200/50">
              <th className="w-16 text-xs font-medium text-base-content/50 text-center">节次</th>
              {days.map(day => (
                <th key={day} className={`min-w-36 px-1 text-center text-xs font-medium xl:min-w-0 ${day >= 6 ? "text-warning/60" : "text-base-content/50"}`}>
                  {DAY_LABELS[day]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periods.map(period => (
              <tr key={period} className="border-t border-base-200/50">
                <td className="text-xs text-base-content/40 text-center font-mono px-1 py-0.5 align-top leading-[72px]">
                  {periodDetailLabel(period)}
                </td>
                {days.map(day => {
                  const slotItems = slotMap.get(`${day}-${period}`);
                  return (
                    <td key={day} className="p-1 align-top min-h-[72px]">
                      {slotItems?.map(({ item, occupiedPeriod, start }) => {
                        const hue = hueMap.get(taskKey(item)) ?? 0;
                        return (
                          <div
                            key={`${item.id}-${occupiedPeriod}`}
							className={`text-[11px] leading-snug mb-1 p-2 rounded-md border-l-[3px] transition-all ${selectedConflictId === item.id ? "ring-2 ring-error ring-offset-1" : ""} ${editable || item.valid === false ? "cursor-pointer hover:brightness-110" : ""} ${item.valid !== false ? "text-base-content" : "text-error"} ${start ? "" : "opacity-75"}`}
                            style={{
                              borderLeftColor: item.valid !== false ? `hsl(${hue}, 65%, 50%)` : undefined,
                              backgroundColor: item.valid !== false ? `hsla(${hue}, 65%, 50%, 0.1)` : undefined,
                            }}
							onClick={() => editable ? onItemClick?.(item) : item.valid === false && onConflictClick?.(item)}
                            title={`${periodRangeLabel(item)}${item.conflictMessage ? ` · ${item.conflictMessage}` : ""}`}
                          >
                            {start && item.valid === false && (
                              <div className="flex items-center gap-1 mb-0.5">
                                <span className="inline-block w-1.5 h-1.5 rounded-full bg-error animate-pulse" />
                                <span className="text-[9px] uppercase tracking-wider font-semibold">冲突</span>
                              </div>
                            )}
                            <div className="font-semibold truncate" style={{ color: `hsl(${hue}, 65%, 60%)` }}>{start ? "" : "↳ "}{item.courseName || "-"}</div>
                            {start ? <>
                              <div className="text-[10px] text-base-content/60 truncate">{item.classGroupName || "-"}</div>
                              <div className="text-[10px] text-base-content/40 truncate">{item.classroomName || "-"} · {item.teacherName || "-"}</div>
                              <div className="mt-1 text-[9px] text-base-content/45">{periodRangeLabel(item)} · 连续{item.consecutiveSlots || 1}节</div>
							  {editable && <div className="mt-1 text-[9px] font-medium text-primary">点击调整片段</div>}
                            </> : <div className="text-[9px] text-base-content/45">{periodRangeLabel(item)} · 第{occupiedPeriod}节占用</div>}
                          </div>
                        );
                      })}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SchemeItemsTable({ items, editable = false, onEdit, onDelete }: { items: SchemeItem[]; editable?: boolean; onEdit?: (item: SchemeItem) => void; onDelete?: (item: SchemeItem) => void }) {
  const hueMap = useMemo(() => buildHueMap(items), [items]);
  return (
    <div className="overflow-x-auto rounded-lg border border-base-300">
      <table className="table table-sm">
        <thead>
          <tr className="text-xs text-base-content/50 uppercase tracking-wider">
            <th className="font-medium w-2"></th>
            <th className="font-medium">周次</th>
            <th className="font-medium">星期</th>
            <th className="font-medium">节次</th>
            <th className="font-medium">课程</th>
            <th className="font-medium">教师</th>
            <th className="font-medium">班级</th>
            <th className="font-medium">教室</th>
            <th className="font-medium">评分</th>
			{editable && <th className="font-medium">操作</th>}
          </tr>
        </thead>
        <tbody>
          {items.map(item => {
            const hue = hueMap.get(taskKey(item)) ?? 0;
            return (
              <tr key={item.id} className={`text-sm transition-colors ${item.valid === false ? "bg-error/5" : ""}`}>
                <td className="w-3 px-0">
                  {item.valid !== false && <span className="inline-block w-full h-full min-h-[1.5rem]" style={{ backgroundColor: `hsl(${hue}, 65%, 50%)` }}>&nbsp;</span>}
                </td>
                <td className="font-mono text-xs">{item.weekNumber}</td>
                <td>{DAY_LABELS[item.dayOfWeek] || item.dayOfWeek}</td>
                <td className="font-mono text-xs">{periodRangeLabel(item)}</td>
                <td className="font-medium">{item.courseName || "-"}</td>
                <td className="text-base-content/70">{item.teacherName || "-"}</td>
                <td className="text-base-content/70">{item.classGroupName || "-"}</td>
                <td className="text-base-content/70 font-mono text-xs">{item.classroomName || "-"}</td>
                <td className="font-mono text-xs text-right">{item.teacherProfileScore != null ? item.teacherProfileScore.toFixed(2) : "-"}</td>
				{editable && <td><div className="flex gap-1"><button className="btn btn-xs btn-ghost" onClick={() => onEdit?.(item)}>调整</button><button className="btn btn-xs btn-ghost text-error" onClick={() => onDelete?.(item)}>删除</button></div></td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ConflictDetails({
  items,
  selectedConflictId,
  onSelect,
}: {
  items: SchemeItem[];
  selectedConflictId: number | null;
  onSelect: (id: number | null) => void;
}) {
  const conflictItems = items.filter(item => item.valid === false);
  const hueMap = useMemo(() => buildHueMap(items), [items]);
  if (conflictItems.length === 0) return null;

  return (
    <details className="collapse collapse-arrow border border-error/30 rounded-lg bg-error/[0.03]" open>
      <summary className="collapse-title text-sm font-medium text-error flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-error" />
        冲突详情（{conflictItems.length} 项）
      </summary>
      <div className="collapse-content p-0">
        <div className="divide-y divide-error/10">
          {conflictItems.map(item => {
            const isSelected = selectedConflictId === item.id;
            const hue = hueMap.get(taskKey(item)) ?? 0;
            return (
              <div
                key={item.id}
                className={`px-4 py-3 flex items-start gap-3 cursor-pointer transition-colors ${isSelected ? "bg-error/[0.08]" : "hover:bg-error/[0.04]"}`}
                onClick={() => onSelect(isSelected ? null : item.id)}
              >
                <div className="w-1 h-full min-h-[3rem] shrink-0 rounded-full mt-0.5" style={{ backgroundColor: `hsl(${hue}, 65%, 50%)` }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-sm flex-wrap">
                    <span className="font-semibold">{item.courseName || "-"}</span>
                    <span className="text-base-content/50">·</span>
                    <span className="text-base-content/60 text-xs">{item.teacherName || "-"}</span>
                    <span className="text-base-content/50">·</span>
                    <span className="text-base-content/60 text-xs">{item.classGroupName || "-"}</span>
                  </div>
                  <div className="text-xs text-base-content/40 mt-0.5">
                    第{item.weekNumber}周 {DAY_LABELS[item.dayOfWeek] || item.dayOfWeek} {periodRangeLabel(item)} · {item.classroomName || "-"}
                  </div>
                  <div className="flex items-start gap-1.5 mt-2 p-2 rounded bg-error/[0.06] text-xs text-error">
                    <span>{item.conflictMessage || "未知冲突"}</span>
                  </div>
                </div>
                {isSelected && <span className="text-xs text-error font-medium shrink-0">查看中</span>}
              </div>
            );
          })}
        </div>
      </div>
    </details>
  );
}
