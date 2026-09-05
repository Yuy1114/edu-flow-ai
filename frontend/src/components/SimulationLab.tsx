import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import request from "../api/request";
import { INITIAL_SIMULATION_CONFIG, profileLabel, simulationRequest, type BoundaryResult, type EngineResult, type FailureAnalysis as FailureAnalysisData, type HourAudit, type SimulationConfig, type SimulationDatasetPreview, type SimulationProfile, type TaskTrace, type TemplateGrid, type TimetableEntry, type TimetableQueryResult } from "../lib/simulation";
import { ALL_PERIODS, periodDetailLabel } from "../lib/schedulingTime";

const PROFILES: { value: SimulationProfile; label: string; description: string }[] = [
  { value: "balanced", label: "均衡学期", description: "容量充足，用于验证完整成功链路。" },
  { value: "formal-mix", label: "正式约束混合", description: "加入助教、禁排、允许周次和教室绑定。" },
  { value: "lab-heavy", label: "上机密集", description: "增加机房课比例，验证专用资源压力。" },
  { value: "constrained", label: "资源紧张", description: "提高并发任务，观察无解原因与容量边界。" },
];

const REASON_LABELS: Record<string, string> = {
  classroom_capacity_unavailable: "没有容量足够的指定类型教室",
  required_room_type_unavailable: "缺少课程要求的教室类型",
  automatic_search_exhausted: "自动搜索已穷尽，转人工复核（未证明无解）",
  allowed_weeks_insufficient: "允许周次不足",
  fixed_or_candidate_classroom_unavailable: "固定或候选教室不可用",
  not_placed: "任务未能进入模板",
};

function Metric({ label, value, detail }: { label: string; value: number | string; detail: string }) {
  return <div className="border border-base-300 bg-base-100 p-3"><div className="text-xs text-base-content/55">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div><div className="mt-1 text-xs text-base-content/45">{detail}</div></div>;
}

export default function SimulationLab() {
  const [config, setConfig] = useState<SimulationConfig>(INITIAL_SIMULATION_CONFIG);
  const [dataset, setDataset] = useState<SimulationDatasetPreview | null>(null);
  const [engineResult, setEngineResult] = useState<EngineResult | null>(null);
  const [boundaryResult, setBoundaryResult] = useState<BoundaryResult | null>(null);
  const [running, setRunning] = useState<"preview" | "run" | "boundary" | null>("preview");

  useEffect(() => {
    let active = true;
    request.post<SimulationDatasetPreview>("/api/ml/simulation/preview", simulationRequest(INITIAL_SIMULATION_CONFIG))
      .then(result => { if (active) setDataset(result); })
      .catch(() => undefined)
      .finally(() => { if (active) setRunning(null); });
    return () => { active = false; };
  }, []);

  function update<K extends keyof SimulationConfig>(key: K, value: SimulationConfig[K]) {
    setConfig(current => ({ ...current, [key]: value }));
    setDataset(null);
    setEngineResult(null);
    setBoundaryResult(null);
  }

  async function generate(nextConfig: SimulationConfig = config) {
    setRunning("preview");
    setEngineResult(null);
    setBoundaryResult(null);
    try {
      setDataset(await request.post<SimulationDatasetPreview>("/api/ml/simulation/preview", simulationRequest(nextConfig)));
    } finally { setRunning(null); }
  }

  async function nextSample() {
    const nextConfig = { ...config, seed: config.seed + 1 };
    setConfig(nextConfig);
    await generate(nextConfig);
  }

  async function runEngine() {
    if (!dataset) return;
    setRunning("run");
    try {
      const result = await request.post<EngineResult>("/api/ml/simulation/run", simulationRequest(config, dataset.simulation_id));
      if (result.dataset.input_hash !== dataset.input_hash) {
        toast.error("排课输入与当前预览不一致，请重新生成模拟数据");
        setDataset(result.dataset);
      }
      setEngineResult(result);
    } finally { setRunning(null); }
  }

  async function scanBoundary() {
    if (!dataset) return;
    setRunning("boundary");
    try { setBoundaryResult(await request.post<BoundaryResult>("/api/ml/simulation/boundary", simulationRequest(config))); }
    finally { setRunning(null); }
  }

  const counts = dataset?.counts;
  const capacityRatio = counts ? Math.round(counts.weekly_slots / Math.max(1, counts.room_week_capacity) * 100) : 0;
  const regularCapacities = dataset
    ? Array.from(new Set(dataset.rooms.filter(room => room.type === "普通教室" && room.capacity < 120).map(room => room.capacity))).sort((a, b) => a - b)
    : [];
  const regularCapacityLabel = regularCapacities.length ? regularCapacities.join("/") : "常规";

  return <div className="mx-auto flex max-w-7xl flex-col gap-5">
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-base-300 pb-4">
      <div><h2 className="text-xl font-semibold">模拟数据实验台</h2><p className="mt-1 text-sm text-base-content/55">按学校教学任务语义生成数据，验证 pattern、动态周模板、硬约束、课时审计和人工复核出口。</p></div>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-ghost btn-sm" onClick={nextSample} disabled={running !== null}>{running === "preview" ? "生成中…" : "下一组样本"}</button>
        <button className="btn btn-outline btn-sm" onClick={() => generate()} disabled={running !== null}>{dataset ? "重新生成当前数据" : "生成当前数据"}</button>
        <button className="btn btn-outline btn-sm" onClick={scanBoundary} disabled={running !== null || !dataset}>{running === "boundary" ? "扫描中…" : "扫描资源边界"}</button>
        <button className="btn btn-primary btn-sm" onClick={runEngine} disabled={running !== null || !dataset}>{running === "run" ? "排课中…" : "运行规则排课"}</button>
      </div>
    </div>

    <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
      <section className="h-fit border border-base-300 bg-base-100 p-4 xl:sticky xl:top-0">
        <div className="flex items-center justify-between"><h3 className="font-semibold">实验配置</h3><span className="badge badge-outline badge-sm">rules-only</span></div>
        <div className="mt-4 space-y-4">
          <fieldset><legend className="mb-2 text-xs text-base-content/55">场景模板</legend><div className="grid gap-2">{PROFILES.map(profile => <label key={profile.value} className={`flex cursor-pointer items-start gap-2 border p-2 ${config.profile === profile.value ? "border-primary bg-primary/10" : "border-base-300"}`}><input className="radio radio-sm radio-primary mt-0.5" type="radio" name="profile" checked={config.profile === profile.value} onChange={() => update("profile", profile.value)} /><span><span className="block text-sm font-medium">{profile.label}</span><span className="block text-xs text-base-content/50">{profile.description}</span></span></label>)}</div></fieldset>
          <Range label="教学任务数" value={config.courses} min={24} max={3000} step={20} onChange={value => update("courses", value)} />
          <Range label="教师数" value={config.teachers} min={8} max={800} step={1} onChange={value => update("teachers", value)} />
          <Range label="班级数" value={config.classGroups} min={6} max={500} step={4} onChange={value => update("classGroups", value)} />
          <Range label="教室数" value={config.classrooms} min={4} max={400} step={4} onChange={value => update("classrooms", value)} />
          <label className="block"><span className="block text-xs text-base-content/55">随机种子</span><input className="input input-bordered input-sm mt-2 w-full font-mono" type="number" value={config.seed} onChange={event => update("seed", Number(event.target.value) || 1)} /></label>
        </div>
        {dataset && <div className="mt-4 space-y-2 border-t border-base-300 pt-3 text-xs text-base-content/50"><div><div>模拟运行 ID</div><code className="mt-1 block text-[10px] text-base-content/70">{dataset.simulation_id}</code></div><div><div>数据集指纹</div><code className="mt-1 block break-all text-[10px] text-base-content/70">{dataset.input_hash.slice(0, 20)}</code></div></div>}
      </section>

      <section className="flex min-w-0 flex-col gap-5">
        {!dataset && <div className="grid min-h-52 place-items-center border border-dashed border-base-300 bg-base-100 p-8 text-center"><div>{running === "preview" && <div className="loading loading-spinner loading-md text-primary" />}<p className="mt-3 text-sm text-base-content/60">{running === "preview" ? "正在由后端生成模拟数据…" : "参数已改变，请生成当前数据后再排课。"}</p></div></div>}
        {dataset && counts && <>
          <div className="grid grid-cols-2 gap-px border border-base-300 bg-base-300 md:grid-cols-4 xl:grid-cols-7">
            <Metric label="教学任务" value={counts.teaching_tasks} detail={`${counts.theory_tasks} 理论 / ${counts.lab_tasks} 上机`} />
            <Metric label="双班任务" value={counts.multi_class_tasks} detail={`${counts.single_class_tasks} 个单班任务`} />
            <Metric label="班级关联" value={counts.class_associations} detail={`覆盖 ${counts.active_class_groups} 个班级`} />
            <Metric label="教师与班级" value={counts.teachers + counts.class_groups} detail={`${counts.teachers} 教师 · ${counts.class_groups} 班`} />
            <Metric label="教室资源" value={counts.classrooms} detail={`${counts.standard_rooms} 普通 · ${counts.lab_rooms} 机房`} />
            <Metric label="周资源负载" value={`${capacityRatio}%`} detail={`${counts.weekly_slots} / ${counts.room_week_capacity} 节`} />
            <Metric label="分层容量预检" value={dataset.resource_capacity_preflight.feasible ? "通过" : "不足"} detail={dataset.resource_capacity_preflight.failed_tiers.length ? `${dataset.resource_capacity_preflight.failed_tiers.length} 个容量层级存在缺口` : "必要容量条件满足"} />
          </div>
          {dataset.warning && <div className="border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning-content">{dataset.warning}</div>}
          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="课程与资源结构" aside={profileLabel(config.profile)}><div className="space-y-4 text-sm"><Distribution label="理论课任务" value={counts.theory_tasks} total={counts.teaching_tasks} color="bg-info" /><Distribution label="上机课任务" value={counts.lab_tasks} total={counts.teaching_tasks} color="bg-secondary" /><Distribution label="普通教室" value={counts.standard_rooms} total={counts.classrooms} color="bg-success" /><Distribution label="机房" value={counts.lab_rooms} total={counts.classrooms} color="bg-warning" /></div></Panel>
            <Panel title="本轮验证重点" aside="规则排课"><ul className="space-y-3 text-sm text-base-content/70"><li className="border-l-2 border-info pl-3">一条任务直接关联一个或两个班，双班来自同专业同年级的固定配对。</li><li className="border-l-2 border-secondary pl-3">连续 2 节理论课、连续 4 节上机课，以及教师/班级/教室冲突。</li><li className="border-l-2 border-warning pl-3">按实际覆盖周动态重构模板，并对每条任务做最终课时审计。</li>{config.profile === "formal-mix" && <li className="border-l-2 border-primary pl-3">正式约束样本：{counts.assistant_teacher_tasks} 条含助教、{counts.teacher_unavailable_tasks} 条含禁排、{counts.allowed_weeks_tasks} 条限定周次、{counts.fixed_classroom_tasks + counts.candidate_classroom_tasks} 条绑定教室。</li>}</ul></Panel>
          </div>
          <div className="grid gap-5 lg:grid-cols-[1.15fr_.85fr]">
            <Panel title="教室容量分布" aside={`总座位 ${counts.room_seats}`}><div className="space-y-4 text-sm"><Distribution label={`普通教室 · ${regularCapacityLabel}座`} value={counts.standard_rooms - counts.large_rooms} total={counts.classrooms} color="bg-success" /><Distribution label="阶梯教室 · 120座" value={counts.large_rooms} total={counts.classrooms} color="bg-info" /><Distribution label="机房 · 48座" value={counts.lab_rooms} total={counts.classrooms} color="bg-warning" /><div className="grid grid-cols-2 gap-3 border-t border-base-200 pt-3 text-xs text-base-content/60"><div>平均任务人数 <b className="ml-1 text-base-content">{counts.average_students}</b></div><div>最大任务人数 <b className="ml-1 text-base-content">{counts.max_task_students}</b></div></div></div></Panel>
            <CapacityPreflight dataset={dataset} />
          </div>
          {counts.capacity_issues > 0 && <CapacityIssues dataset={dataset} />}
          {engineResult && <EngineResultView result={engineResult} />}
          {boundaryResult && <BoundaryView result={boundaryResult} />}
          <TaskPreview dataset={dataset} />
        </>}
      </section>
    </div>
    {engineResult && <TimetableExplorer simulationId={engineResult.simulation_id} />}
  </div>;
}

function Range({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return <label className="block"><span className="block text-xs text-base-content/55">{label} <b className="ml-1 text-base-content">{value}</b></span><input className="range range-primary range-xs mt-2 block w-full" type="range" min={min} max={max} step={step} value={value} onChange={event => onChange(Number(event.target.value))} /></label>;
}

function Panel({ title, aside, children }: { title: string; aside: string; children: ReactNode }) {
  return <div className="border border-base-300 bg-base-100 p-4"><div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">{title}</h3><span className="text-xs text-base-content/45">{aside}</span></div>{children}</div>;
}

function CapacityIssues({ dataset }: { dataset: SimulationDatasetPreview }) {
  return <div className="border border-error/40 bg-base-100"><div className="flex items-center justify-between border-b border-base-300 px-4 py-3"><h3 className="font-semibold">超容量任务样本</h3><span className="text-xs text-error">显示前 {dataset.capacity_issues_preview.length} 条</span></div><div className="overflow-x-auto"><table className="table table-sm"><thead><tr><th>任务</th><th>课程</th><th>班级</th><th>人数</th><th>可用容量</th><th>缺口</th></tr></thead><tbody>{dataset.capacity_issues_preview.map(task => <tr key={task.id}><td className="font-mono text-xs">{task.id}</td><td>{task.course}</td><td>{task.class_names.join("、")}</td><td>{task.students}</td><td>{task.available_capacity}</td><td className="font-medium text-error">+{task.students - task.available_capacity}</td></tr>)}</tbody></table></div></div>;
}

function CapacityPreflight({ dataset }: { dataset: SimulationDatasetPreview }) {
  const preflight = dataset.resource_capacity_preflight;
  return <div className={`border p-4 ${preflight.feasible ? "border-success/40 bg-success/5" : "border-error/40 bg-error/5"}`}><div className="flex items-center justify-between"><h3 className="font-semibold">资源分层必要容量</h3><span className={`badge badge-sm ${preflight.feasible ? "badge-success" : "badge-error"}`}>{preflight.feasible ? "通过" : "必然容量不足"}</span></div><p className="mt-2 text-xs text-base-content/60">按房型和最小座位逐层比对 18 周工作日白天需求与供给；通过是必要条件，不代表已证明可排。</p><div className="mt-3 max-h-36 space-y-1 overflow-y-auto text-xs">{preflight.tiers.map(tier => <div key={`${tier.room_type}-${tier.minimum_capacity}`} className="grid grid-cols-[1fr_auto] gap-3 border-t border-base-300 pt-1"><span>{tier.room_type} · ≥{tier.minimum_capacity}座 · {tier.room_count}间</span><span className={tier.feasible ? "text-base-content/60" : "font-medium text-error"}>{tier.demand_hours}/{tier.supply_hours} 课时</span></div>)}</div></div>;
}

function EngineResultView({ result }: { result: EngineResult }) {
  const schedule = result.summary.schedule;
  const statusStyle = result.summary.status === "ok" ? "badge-success" : result.summary.status === "invalid" ? "badge-error" : "badge-warning";
  const statusText = result.summary.status === "ok" ? "自动排课完成" : result.summary.status === "invalid" ? "存在硬约束错误" : "需要人工复核";
  return <section className="border border-base-300 bg-base-100"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 px-4 py-3"><div><h3 className="font-semibold">规则排课结果</h3><p className="mt-1 text-xs text-base-content/50">按绝对周次占位并动态重构周模板；本阶段未启用 Placement Model。</p></div><span className={`badge ${statusStyle}`}>{statusText}</span></div><div className="grid grid-cols-2 gap-px bg-base-300 md:grid-cols-4"><Metric label="教学任务" value={result.engine.teaching_task_count} detail={`${result.dataset.counts.multi_class_tasks} 个双班任务`} /><Metric label="自动完成" value={schedule.completed} detail={`生成 ${schedule.template_count} 张动态模板`} /><Metric label="转人工复核" value={schedule.remaining} detail={schedule.remaining ? "未证明无解，可用保留时段调整" : "没有未排任务"} /><Metric label="硬约束错误" value={result.summary.hard_constraint_error_count} detail="仅统计冲突、容量和无效 pattern" /></div><HourAuditView audit={schedule.hour_audit} />{schedule.remaining > 0 && <FailureAnalysis analyses={result.failure_analysis ?? []} />}<div className="border-t border-base-300 p-4"><h4 className="mb-3 text-sm font-semibold">动态模板负载</h4><div className="grid gap-4 xl:grid-cols-2">{result.template_grids.map(grid => <TemplateGridView key={grid.template_id} grid={grid} />)}</div></div><TaskTraceView traces={result.task_traces ?? []} />{result.unresolved_preview.length > 0 && <div className="border-t border-base-300 px-4 py-3 text-xs text-base-content/60">待人工复核样本：{result.unresolved_preview.slice(0, 6).map(row => `${row.course}（${REASON_LABELS[row.reason] ?? row.reason}）`).join("；")}</div>}<div className="border-t border-base-300 px-4 py-2 text-[10px] text-base-content/45">本次运行已持久化：{(result.artifact_files ?? []).join(" · ")}</div></section>;
}

function HourAuditView({ audit }: { audit: HourAudit }) {
  const mismatches = audit.tasks.filter(task => task.status !== "exact");
  const rows = mismatches.length ? mismatches.slice(0, 50) : audit.tasks.slice(0, 20);
  return <div className="border-t border-base-300 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="text-sm font-semibold">最终课时审计</h4><p className="mt-1 text-xs text-base-content/50">课时差是待人工微调项，不计入硬约束冲突。</p></div><span className={`badge badge-sm ${audit.mismatch_count ? "badge-warning" : "badge-success"}`}>{audit.mismatch_count ? `${audit.mismatch_count} 个任务有差异` : "全部精确"}</span></div><div className="mt-3 grid grid-cols-2 gap-px border border-base-300 bg-base-300 md:grid-cols-4"><Metric label="要求总课时" value={audit.required_total_hours} detail={`${audit.tasks.length} 个教学任务`} /><Metric label="已排总课时" value={audit.scheduled_total_hours} detail={`总差额 ${audit.delta_total_hours >= 0 ? "+" : ""}${audit.delta_total_hours}`} /><Metric label="多排" value={audit.over_task_count} detail={`${audit.over_hours} 课时`} /><Metric label="少排" value={audit.under_task_count} detail={`${audit.under_hours} 课时`} /></div><details className="mt-3 border border-base-300"><summary className="cursor-pointer px-3 py-2 text-xs font-medium">逐任务审计 · {mismatches.length ? `优先显示前 ${rows.length} 条差异` : `显示前 ${rows.length} 条精确结果`}</summary><div className="overflow-x-auto border-t border-base-300"><table className="table table-xs"><thead><tr><th>任务</th><th>课程</th><th>要求</th><th>Pattern</th><th>已排</th><th>差额</th><th>结论</th></tr></thead><tbody>{rows.map(task => <tr key={task.uid}><td className="font-mono">{task.uid}</td><td>{task.course}</td><td>{task.required_hours}</td><td>{task.pattern_hours}</td><td>{task.scheduled_hours}</td><td className={task.delta_hours === 0 ? "" : "text-warning"}>{task.delta_hours > 0 ? "+" : ""}{task.delta_hours}</td><td>{task.status === "exact" ? "精确" : task.status === "over" ? "多排，待微调" : task.placed ? "少排，待微调" : "未排，待人工决定"}</td></tr>)}</tbody></table></div></details></div>;
}

function TaskTraceView({ traces }: { traces: TaskTrace[] }) {
  return <div className="border-t border-base-300 p-4"><div className="mb-3"><h4 className="text-sm font-semibold">教学任务链路追踪</h4><p className="mt-1 text-xs text-base-content/50">输入任务 → pattern → 绝对周次占位 → 动态模板片段；显示前 {traces.length} 条。</p></div><div className="grid gap-2">{traces.slice(0, 12).map(trace => <details key={trace.source_key} className="border border-base-300 bg-base-100"><summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2 text-sm"><code className="text-xs">{trace.source_key}</code><span className="font-medium">{trace.course}</span><span className={`badge badge-sm ${trace.status === "scheduled" ? "badge-success" : "badge-warning"}`}>{trace.status === "scheduled" ? "已排" : "待人工复核"}</span><span className="ml-auto text-xs text-base-content/45">{trace.templates.join(" + ") || "未进入动态模板"}</span></summary><div className="grid gap-3 border-t border-base-300 p-3 text-xs md:grid-cols-3"><div><div className="text-base-content/45">1 · 教学任务</div><div className="mt-1">{trace.teacher} · {trace.classes.join("、")}</div><div>{trace.pattern.total_hours} 课时 · {trace.pattern.room_type}</div></div><div><div className="text-base-content/45">2 · Pattern</div><div className="mt-1">每周 {trace.pattern.sessions_per_week} 次 × 连续 {trace.pattern.consecutive_slots} 节</div><div>持续 {trace.pattern.duration_weeks} 周 · {trace.pattern.source}</div></div><div><div className="text-base-content/45">3 · 动态模板片段</div>{trace.fragments.length ? trace.fragments.map(fragment => <div key={`${fragment.fragment_id}-${fragment.template_id}`} className="mt-1">{fragment.template_id} · {fragment.week_label} · 周{fragment.day} 第{fragment.period}节 · {fragment.room}</div>) : <div className="mt-1 text-warning">{REASON_LABELS[trace.failure?.reason ?? "not_placed"] ?? trace.failure?.reason}</div>}</div></div></details>)}</div></div>;
}

function FailureAnalysis({ analyses }: { analyses: FailureAnalysisData[] }) {
  return <div className="border-t border-base-300 p-4"><h4 className="text-sm font-semibold text-error">失败原因分析</h4><div className="mt-2 grid gap-3 lg:grid-cols-2">{analyses.map(item => <div key={item.reason} className="border border-error/20 bg-error/5 p-3 text-sm"><div><b>{item.count}</b> 个 · {REASON_LABELS[item.reason] ?? item.reason}</div><p className="mt-1 text-xs text-base-content/60">{item.message}</p><div className="mt-2 text-xs"><span className="text-base-content/45">建议：</span>{item.suggestions.join("；")}</div>{item.examples.length > 0 && <div className="mt-2 border-t border-error/10 pt-2 text-[11px] text-base-content/55">样本：{item.examples.map(example => `${example.uid} ${example.course}`).join("；")}</div>}<div className="mt-1 font-mono text-[10px] text-base-content/40">{item.category} · {item.reason}</div></div>)}</div></div>;
}

type TimetableFilters = { template_id: string; teacher: string; class_name: string; classroom: string; course: string };
const EMPTY_TIMETABLE_FILTERS: TimetableFilters = { template_id: "", teacher: "", class_name: "", classroom: "", course: "" };

function TimetableExplorer({ simulationId }: { simulationId: string }) {
  const [draft, setDraft] = useState<TimetableFilters>(EMPTY_TIMETABLE_FILTERS);
  const [applied, setApplied] = useState<TimetableFilters>(EMPTY_TIMETABLE_FILTERS);
  const [result, setResult] = useState<TimetableQueryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"grid" | "list">("grid");

  async function query(filters: TimetableFilters, page = 1) {
    setLoading(true);
    try {
      const data = await request.post<TimetableQueryResult>("/api/ml/simulation/timetable", {
        simulation_id: simulationId,
        ...Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, value || null])),
        page,
        page_size: 200,
      });
      setApplied(filters);
      setResult(data);
      return data;
    } finally { setLoading(false); }
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    request.post<TimetableQueryResult>("/api/ml/simulation/timetable", {
      simulation_id: simulationId, page: 1, page_size: 200,
    }).then(async initial => {
      if (!active) return;
      const teacher = initial.filters.teachers[0] ?? "";
      if (!teacher) {
        setResult(initial);
        setLoading(false);
        return;
      }
      const initialFilters = { ...EMPTY_TIMETABLE_FILTERS, teacher };
      setDraft(initialFilters);
      setApplied(initialFilters);
      const selected = await request.post<TimetableQueryResult>("/api/ml/simulation/timetable", {
        simulation_id: simulationId, teacher, page: 1, page_size: 200,
      });
      if (active) setResult(selected);
    }).catch(() => undefined).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [simulationId]);

  const options = result?.filters;
  function updateFilter(key: keyof TimetableFilters, value: string) {
    setDraft(current => ({ ...current, [key]: value }));
  }
  function clearFilters() {
    setDraft(EMPTY_TIMETABLE_FILTERS);
    void query(EMPTY_TIMETABLE_FILTERS);
  }

  return <section className="border border-base-300 bg-base-100">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-base-300 px-4 py-4">
      <div><h3 className="text-lg font-semibold">课表综合查询</h3><p className="mt-1 text-sm text-base-content/55">按班级、教师、教室、课程和动态模板组合查询本次排课方案。每张模板都显示实际覆盖周次。</p></div>
      <div className="join"><button className={`btn join-item btn-sm ${view === "grid" ? "btn-active" : "btn-ghost"}`} onClick={() => setView("grid")}>课表视图</button><button className={`btn join-item btn-sm ${view === "list" ? "btn-active" : "btn-ghost"}`} onClick={() => setView("list")}>明细列表</button></div>
    </div>
    <div className="border-b border-base-300 bg-base-200/40 p-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <FilterSelect label="动态模板" value={draft.template_id} options={options?.templates ?? []} onChange={value => updateFilter("template_id", value)} />
        <FilterSelect label="教师" value={draft.teacher} options={options?.teachers ?? []} onChange={value => updateFilter("teacher", value)} />
        <FilterSelect label="班级" value={draft.class_name} options={options?.classes ?? []} onChange={value => updateFilter("class_name", value)} />
        <FilterSelect label="教室" value={draft.classroom} options={options?.classrooms ?? []} onChange={value => updateFilter("classroom", value)} />
        <label className="block"><span className="text-xs text-base-content/55">课程名称或代码</span><input className="input input-bordered input-sm mt-1 w-full" value={draft.course} placeholder="输入关键词" onChange={event => updateFilter("course", event.target.value)} onKeyDown={event => { if (event.key === "Enter") void query(draft); }} /></label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2"><button className="btn btn-primary btn-sm" disabled={loading} onClick={() => void query(draft)}>{loading ? <span className="loading loading-spinner loading-xs" /> : null}查询课表</button><button className="btn btn-ghost btn-sm" disabled={loading} onClick={clearFilters}>清空条件</button><span className="ml-auto text-xs text-base-content/45">条件可叠加；候选项来自当前模拟方案</span></div>
    </div>
    {result && <>
      <div className="grid grid-cols-2 gap-px border-b border-base-300 bg-base-300 md:grid-cols-6"><Metric label="模板片段" value={result.summary.fragments} detail={`${result.summary.semester_occupied_segments} 个学期占用节次`} /><Metric label="课程" value={result.summary.courses} detail="当前条件内" /><Metric label="教师" value={result.summary.teachers} detail="去重统计" /><Metric label="班级" value={result.summary.classes} detail="含双班任务的两个班" /><Metric label="教室" value={result.summary.classrooms} detail="去重统计" /><Metric label="结果页" value={`${result.page}/${result.page_count}`} detail={`每页 ${result.page_size} 条`} /></div>
      {result.total > result.entries.length && view === "grid" && <div className="border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs">当前共有 {result.total} 条，课表视图只展示本页 {result.entries.length} 条；请增加过滤条件获得可读课表。</div>}
      {loading ? <div className="grid min-h-72 place-items-center"><span className="loading loading-spinner loading-lg text-primary" /></div> : result.entries.length === 0 ? <div className="grid min-h-52 place-items-center text-sm text-base-content/50">没有符合当前组合条件的排课安排</div> : view === "grid" ? <LargeTimetable entries={result.entries} /> : <TimetableList result={result} onPage={page => void query(applied, page)} />}
    </>}
  </section>;
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <label className="block"><span className="text-xs text-base-content/55">{label}</span><select className="select select-bordered select-sm mt-1 w-full" value={value} onChange={event => onChange(event.target.value)}><option value="">全部{label}</option>{options.map(option => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function LargeTimetable({ entries }: { entries: TimetableEntry[] }) {
  const templates = Array.from(new Set(entries.map(entry => entry.template_id)));
  return <div className="space-y-6 p-4">{templates.map(templateId => {
    const templateEntries = entries.filter(entry => entry.template_id === templateId);
    const weekLabel = templateEntries[0]?.week_label ?? "未指定周次";
    return <div key={templateId}><div className="mb-3 flex items-center justify-between"><div><h4 className="font-semibold">{templateId}</h4><p className="text-xs text-base-content/45">{weekLabel} · {templateEntries.length} 个排课片段 · 第9-10节为人工调课保留位</p></div></div><div className="overflow-x-auto border border-base-300"><div className="grid min-w-[1120px] grid-cols-[88px_repeat(5,minmax(200px,1fr))] bg-base-300 gap-px"><div className="bg-base-200 p-3 text-center text-xs font-medium">45分钟节次</div>{["星期一", "星期二", "星期三", "星期四", "星期五"].map(day => <div key={day} className="bg-base-200 p-3 text-center text-sm font-medium">{day}</div>)}{ALL_PERIODS.flatMap(period => {
      return [<div key={`p-${period}`} className={`flex min-h-32 items-start justify-center bg-base-200 p-3 text-xs font-semibold ${period > 8 ? "text-warning" : ""}`}>{periodDetailLabel(period)}</div>, ...Array.from({ length: 5 }, (_, dayIndex) => {
        const cellEntries = templateEntries.filter(entry => entry.day === dayIndex + 1 && entry.start_period === period);
        return <div key={`${dayIndex + 1}-${period}`} className="min-h-32 bg-base-100 p-2">{cellEntries.slice(0, 3).map(entry => <TimetableCard key={entry.fragment_id} entry={entry} />)}{cellEntries.length > 3 && <div className="mt-1 text-center text-xs text-base-content/45">另有 {cellEntries.length - 3} 项</div>}</div>;
      })];
    })}</div></div></div>;
  })}</div>;
}

function TimetableCard({ entry }: { entry: TimetableEntry }) {
  return <div className={`mb-2 border-l-4 p-2 text-xs ${entry.room_type === "机房" ? "border-secondary bg-secondary/10" : "border-info bg-info/10"}`}><div className="font-semibold leading-snug">{entry.course}</div><div className="mt-1 text-base-content/70">{entry.teacher}</div><div className="mt-0.5 line-clamp-2 text-base-content/60">{entry.classes.join("、")}</div><div className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-base-content/50"><span>{entry.classroom}</span><span>第{entry.start_period}–{entry.end_period}节</span><span>{entry.week_label}</span></div></div>;
}

function TimetableList({ result, onPage }: { result: TimetableQueryResult; onPage: (page: number) => void }) {
  return <div><div className="overflow-x-auto"><table className="table table-sm"><thead><tr><th>动态模板</th><th>星期 / 节次</th><th>课程</th><th>教师</th><th>班级</th><th>教室</th><th>覆盖周 / 课时</th><th>人数</th></tr></thead><tbody>{result.entries.map(entry => <tr key={`${entry.template_id}-${entry.fragment_id}`}><td><span className="badge badge-ghost badge-sm">{entry.template_id}</span></td><td>周{["", "一", "二", "三", "四", "五"][entry.day]} · {entry.start_period}–{entry.end_period}</td><td><div className="font-medium">{entry.course}</div><div className="font-mono text-[10px] text-base-content/40">{entry.course_code}</div></td><td>{entry.teacher}</td><td className="max-w-56 whitespace-normal">{entry.classes.join("、")}</td><td>{entry.classroom}<div className="text-[10px] text-base-content/45">{entry.room_type}</div></td><td>{entry.week_label}<div className="text-[10px] text-base-content/45">本模板贡献 {entry.covered_hours} 课时</div></td><td>{entry.student_count}</td></tr>)}</tbody></table></div><div className="flex items-center justify-between border-t border-base-300 p-3 text-xs"><span>共 {result.total} 条，第 {result.page}/{result.page_count} 页</span><div className="join"><button className="btn join-item btn-sm" disabled={result.page <= 1} onClick={() => onPage(result.page - 1)}>上一页</button><button className="btn join-item btn-sm" disabled={result.page >= result.page_count} onClick={() => onPage(result.page + 1)}>下一页</button></div></div></div>;
}

function BoundaryView({ result }: { result: BoundaryResult }) {
  return <section className="border border-base-300 bg-base-100"><div className="border-b border-base-300 px-4 py-3"><h3 className="font-semibold">资源递减边界</h3><p className="mt-1 text-xs text-base-content/50">保持同一批教学任务、教师、班级和随机种子，只递减教室数。</p></div><div className="overflow-x-auto"><table className="table table-sm"><thead><tr><th>教室数</th><th>状态</th><th>自动完成</th><th>转人工</th><th>主要原因</th></tr></thead><tbody>{result.rows.map(row => <tr key={row.classrooms}><td>{row.classrooms}</td><td><span className={`badge badge-sm ${row.status === "ok" ? "badge-success" : row.status === "invalid" ? "badge-error" : "badge-warning"}`}>{row.status === "ok" ? "完成" : row.status === "invalid" ? "无效" : "需复核"}</span></td><td>{row.completed}</td><td>{row.remaining}</td><td className="text-xs">{Object.keys(row.reasons).length ? Object.entries(row.reasons).map(([reason, count]) => `${REASON_LABELS[reason] ?? reason} ${count}`).join("；") : "—"}</td></tr>)}</tbody></table></div></section>;
}

function TaskPreview({ dataset }: { dataset: SimulationDatasetPreview }) {
  return <div className="border border-base-300 bg-base-100"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 px-4 py-3"><div><h3 className="font-semibold">后端教学任务预览</h3><p className="mt-1 text-xs text-base-content/50">一行就是一条教学任务；双班关系已直接写入任务，不再由两行合并。</p></div><span className="text-xs text-base-content/45">显示 {dataset.tasks_preview.length} 条，共 {dataset.counts.teaching_tasks} 条</span></div><div className="overflow-x-auto"><table className="table table-sm"><thead><tr><th>任务</th><th>课程</th><th>类型</th><th>教师</th><th>任务内班级</th><th>班级关联数</th><th>合计人数</th><th>节奏</th><th>资源</th></tr></thead><tbody>{dataset.tasks_preview.map(task => <tr key={task.id}><td className="font-mono text-xs">{task.id}</td><td>{task.course}</td><td><span className={`badge badge-sm ${task.type === "上机课" ? "badge-secondary" : "badge-info"}`}>{task.type}</span></td><td>{task.teacher}</td><td>{task.class_names.join("、")}</td><td><span className={`badge badge-sm ${task.class_count === 2 ? "badge-primary" : "badge-ghost"}`}>{task.class_count === 2 ? "双班" : "单班"}</span></td><td>{task.students}</td><td>{task.sessions}次/周 · {task.hours}h/{task.weeks}周</td><td>{task.room_type}</td></tr>)}</tbody></table></div></div>;
}

function TemplateGridView({ grid }: { grid: TemplateGrid }) {
  const cellByKey = new Map(grid.cells.map(cell => [`${cell.day}-${cell.period}`, cell]));
  return <div className="min-w-0"><div className="mb-2 flex items-center justify-between"><h4 className="text-sm font-semibold">{grid.template_id}</h4><span className="text-xs text-base-content/50">{grid.week_label} · 晚间保留人工位</span></div><div className="overflow-x-auto"><table className="table table-xs table-fixed border border-base-300"><thead><tr><th>45分钟节次</th>{["一", "二", "三", "四", "五"].map(day => <th key={day}>周{day}</th>)}</tr></thead><tbody>{ALL_PERIODS.map(period => <tr key={period}><th className={period > 8 ? "text-warning" : ""}>{periodDetailLabel(period)}</th>{Array.from({ length: 5 }, (_, dayIndex) => { const cell = cellByKey.get(`${dayIndex + 1}-${period}`); const first = cell?.items[0]; return <td key={dayIndex} className="align-top text-[10px] leading-tight"><div className="font-medium tabular-nums">{cell?.count ?? 0} 项</div>{first && <div className="mt-1 truncate" title={`${first.course_name} · ${first.class_names}`}>{first.course_name}</div>}</td>; })}</tr>)}</tbody></table></div></div>;
}

function Distribution({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const width = Math.max(3, Math.round(value / Math.max(1, total) * 100));
  return <div><div className="mb-1 flex justify-between text-xs"><span>{label}</span><span className="tabular-nums text-base-content/55">{value} · {width}%</span></div><div className="h-2 bg-base-200"><div className={`h-full ${color}`} style={{ width: `${width}%` }} /></div></div>;
}
