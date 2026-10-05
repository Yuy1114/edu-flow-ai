import type { TeacherSatisfactionEntry, TeacherSatisfactionView } from "../hooks/useAllocation";

/** 与生成侧（Python teacher_preferences）同一阈值，只用于文案说明；结论读后端那一列。 */
const LOW_SATISFACTION_THRESHOLD = 0.7;

const COMPONENT_LABELS: Record<string, string> = {
  early_period: "早间时段",
  late_period: "晚间时段",
  preferred_weekday: "偏好星期",
  preferred_period: "偏好节次",
  daily_load: "每日课时上限",
  room_type: "偏好教室类型",
};

export function componentLabel(dimension: string) {
  return COMPONENT_LABELS[dimension] || dimension;
}

/**
 * 把"哪一维没被满足"翻成人话：数字来自生成侧写进 evidence 的原始计数，
 * 不在这里另算一遍，免得页面和排课引擎各说一套。
 */
export function describeSatisfactionReason(entry: TeacherSatisfactionEntry) {
  const dimension = entry.primaryReasonDimension;
  if (!dimension) return "未声明任何软偏好";
  const evidence = entry.evidence || {};
  switch (dimension) {
    case "early_period":
      return `第1-2节排了 ${evidence.early_item_count ?? 0} 次`;
    case "late_period":
      return `晚间排了 ${evidence.late_item_count ?? 0} 次`;
    case "preferred_weekday":
      return `偏好星期命中 ${evidence.preferred_weekday_hits ?? 0}/${entry.itemCount}`;
    case "preferred_period":
      return `偏好节次命中 ${evidence.preferred_period_hits ?? 0}/${entry.itemCount}`;
    case "daily_load":
      return evidence.max_daily_lessons
        ? `${evidence.overloaded_days ?? 0} 天超过每日 ${evidence.max_daily_lessons} 次`
        : `${evidence.overloaded_days ?? 0} 天超量`;
    case "room_type":
      return `偏好教室命中 ${evidence.preferred_room_type_hits ?? 0}/${entry.itemCount}`;
    default:
      return `${componentLabel(dimension)}得分 ${(entry.primaryReasonScore ?? 0).toFixed(2)}`;
  }
}

function scoreTone(score: number) {
  if (score < 0.5) return "text-error";
  if (score < LOW_SATISFACTION_THRESHOLD) return "text-warning";
  return "text-base-content/70";
}

function EntryRow({
  entry,
  templateLabel,
  showTemplate,
}: {
  entry: TeacherSatisfactionEntry;
  templateLabel: (code: string) => string;
  showTemplate?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs">
      <span className="font-medium text-base-content/85 min-w-20">{entry.teacherName || "-"}</span>
      {showTemplate && (
        <span className="badge badge-xs badge-ghost shrink-0">{templateLabel(entry.templateCode)}</span>
      )}
      <span className="text-base-content/60">
        主因：{componentLabel(entry.primaryReasonDimension || "")} · {describeSatisfactionReason(entry)}
      </span>
      <span className="ml-auto flex items-center gap-3 shrink-0 font-mono">
        <span className={`${scoreTone(entry.preferenceScore)}`} title="只看教师已声明的维度">
          偏好 {entry.preferenceScore.toFixed(2)}
        </span>
        <span className="text-base-content/45" title="六分量等权，与 AI 侧方案满意度同口径">
          满足 {entry.satisfactionScore.toFixed(2)}
        </span>
        <span className="text-base-content/35">{entry.itemCount} 次 / {entry.daysUsed} 天</span>
      </span>
    </div>
  );
}

export function TeacherSatisfactionPanel({
  satisfaction,
  templateLabels,
}: {
  satisfaction?: TeacherSatisfactionView | null;
  templateLabels?: Record<string, string>;
}) {
  // 本次生成没有画像参与：整段不出现，也不解释（没有画像时它列不出任何东西）。
  if (!satisfaction?.profileApplied) return null;

  const label = (code: string) => templateLabels?.[code] || code;
  const lowCount = satisfaction.lowSatisfactionTeachers.length;

  return (
    <div className="card bg-base-100 shadow-sm border border-base-300">
      <div className="card-body p-4 gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-base-content/70">教师画像满足度</h3>
            <span className="badge badge-xs badge-ghost">按模板（方案）分别统计</span>
          </div>
          <span className="text-[11px] text-base-content/45">
            偏好满足度只看教师声明过的维度，低于 {LOW_SATISFACTION_THRESHOLD} 记低满足
          </span>
        </div>

        <div className="flex flex-wrap gap-3">
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[110px] flex-1">
            <div className="stat-title text-xs text-base-content/60">覆盖教师</div>
            <div className="stat-value text-lg text-info">{satisfaction.teacherCount}</div>
            <div className="stat-desc text-[10px] text-base-content/40">声明了软偏好的教师</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[110px] flex-1">
            <div className="stat-title text-xs text-base-content/60">偏好满足度</div>
            <div className="stat-value text-lg text-primary">{satisfaction.averagePreferenceScore.toFixed(3)}</div>
            <div className="stat-desc text-[10px] text-base-content/40">已声明维度平均</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[110px] flex-1">
            <div className="stat-title text-xs text-base-content/60">方案满足度</div>
            <div className="stat-value text-lg">{satisfaction.averageSatisfactionScore.toFixed(3)}</div>
            <div className="stat-desc text-[10px] text-base-content/40">六分量等权，旧口径可比</div>
          </div>
          <div className="stat bg-base-100 border border-base-300 rounded-lg p-3 min-w-[110px] flex-1">
            <div className="stat-title text-xs text-base-content/60">低满足教师</div>
            <div className={`stat-value text-lg ${satisfaction.lowSatisfactionCount > 0 ? "text-warning" : "text-success"}`}>
              {satisfaction.lowSatisfactionCount}
            </div>
            <div className="stat-desc text-[10px] text-base-content/40">
              {satisfaction.lowSatisfactionCount > 0 ? "有至少一份模板没排好" : "全部达标"}
            </div>
          </div>
        </div>

        {lowCount > 0 && (
          <details className="collapse collapse-arrow border border-warning/30 rounded-lg bg-warning/[0.04]" open>
            <summary className="collapse-title text-sm font-medium text-warning">
              低满足教师与主因（{lowCount} 项，按模板列出）
            </summary>
            <div className="collapse-content p-0">
              <div className="divide-y divide-warning/10">
                {satisfaction.lowSatisfactionTeachers.map(entry => (
                  <EntryRow
                    key={`${entry.templateCode}-${entry.teacherKey}`}
                    entry={entry}
                    templateLabel={label}
                    showTemplate
                  />
                ))}
              </div>
            </div>
          </details>
        )}

        <details className="collapse collapse-arrow border border-base-300 rounded-lg">
          <summary className="collapse-title text-sm font-medium text-base-content/60">
            全部教师读数（{satisfaction.teachers.length} 条）
          </summary>
          <div className="collapse-content p-0">
            <div className="divide-y divide-base-200">
              {satisfaction.teachers.map(entry => (
                <EntryRow
                  key={`${entry.templateCode}-${entry.teacherKey}`}
                  entry={entry}
                  templateLabel={label}
                  showTemplate
                />
              ))}
            </div>
          </div>
        </details>
      </div>
    </div>
  );
}
