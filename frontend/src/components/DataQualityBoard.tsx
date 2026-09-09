import { useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import request from "../api/request";
import { ALL_PERIODS, periodDetailLabel, periodSegment } from "../lib/schedulingTime";
import {
  DAY_LABELS, HEAT_LEGEND, P, T, filterPlacements, filterTasks, formatCount, hasWeek,
  heatClass, roomGrid, slotGrid, weekCount, weeksOf,
  type DatasetBoard, type DatasetSnapshot, type PlacementRow,
} from "../lib/dataQuality";

type ViewId = "overview" | "slots" | "classes" | "rooms" | "courses" | "joint";

const VIEWS: { id: ViewId; no: string; label: string }[] = [
  { id: "overview", no: "01", label: "清洗总览" },
  { id: "slots", no: "02", label: "时段分布" },
  { id: "classes", no: "03", label: "班级课表" },
  { id: "rooms", no: "04", label: "教室占用" },
  { id: "courses", no: "05", label: "课程与任务" },
  { id: "joint", no: "06", label: "合班还原" },
];

const SEARCHABLE: Partial<Record<ViewId, string>> = { classes: "班级", rooms: "教室", courses: "课程" };

/** 18 周 × 工作日 × 第 1-8 节。教室占用率以此为分母，超过 100% 说明用到了晚间或周末。 */
const WEEKDAY_DAYTIME_CAPACITY = 18 * 5 * 8;

function Panel({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="border border-base-300 bg-base-100">
      <div className="border-b border-base-300 px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description ? <p className="mt-1 max-w-4xl text-xs leading-relaxed text-base-content/55">{description}</p> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: string; tone?: "warn" | "accent" }) {
  const toneClass = tone === "warn" ? "border-warning/40 bg-warning/10" : tone === "accent" ? "border-primary/40 bg-primary/10" : "border-base-300 bg-base-100";
  return (
    <div className={`border p-3 ${toneClass}`}>
      <div className="text-xs text-base-content/55">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {detail ? <div className="mt-1 text-xs text-base-content/45">{detail}</div> : null}
    </div>
  );
}

function Bar({ label, value, max, tone }: { label: string; value: number; max: number; tone?: "warn" | "mute" }) {
  const fill = tone === "warn" ? "bg-warning" : tone === "mute" ? "bg-base-content/25" : "bg-primary";
  return (
    <div className="grid grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-3 text-xs">
      <span className="truncate text-base-content/70">{label}</span>
      <span className="h-3 bg-base-200"><span className={`block h-full ${fill}`} style={{ width: `${max ? (value / max) * 100 : 0}%` }} /></span>
      <span className="w-16 text-right tabular-nums text-base-content/55">{formatCount(value)}</span>
    </div>
  );
}

function HeatTable({ grid, max, unit }: { grid: number[][]; max: number; unit: string }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[34rem] grid-cols-[6rem_repeat(7,minmax(3.2rem,1fr))] gap-[3px]">
        <div />
        {DAY_LABELS.map(day => <div key={day} className="py-1 text-center text-xs font-medium text-base-content/55">{day}</div>)}
        {ALL_PERIODS.map(period => (
          <PeriodRow key={period} period={period} row={grid[period]} max={max} unit={unit} />
        ))}
      </div>
    </div>
  );
}

function PeriodRow({ period, row, max, unit }: { period: number; row: number[]; max: number; unit: string }) {
  return (
    <>
      <div className={`flex items-center gap-1 text-xs text-base-content/70 ${period === 9 ? "border-t border-dashed border-base-300 pt-1" : ""}`}>
        第{period}节<span className="text-[10px] text-base-content/40">{periodSegment(period)}</span>
      </div>
      {DAY_LABELS.map((day, index) => {
        const value = row[index + 1];
        return (
          <div
            key={day}
            title={`${day} 第${period}节：${formatCount(value)} ${unit}`}
            className={`py-2 text-center text-xs tabular-nums ${heatClass(value, max)} ${period === 9 ? "mt-1" : ""}`}
          >
            {value ? formatCount(value) : "·"}
          </div>
        );
      })}
    </>
  );
}

export default function DataQualityBoard() {
  const [board, setBoard] = useState<DatasetBoard | null>(null);
  const [snapshots, setSnapshots] = useState<DatasetSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [capturing, setCapturing] = useState(false);
  const [view, setView] = useState<ViewId>("overview");
  const [semester, setSemester] = useState(-1);
  const [trainableOnly, setTrainableOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedClass, setSelectedClass] = useState<number | null>(null);
  const [selectedRoom, setSelectedRoom] = useState<number | null>(null);
  const [week, setWeek] = useState(1);

  useEffect(() => {
    let active = true;
    request.get<DatasetBoard>("/api/ml/dataset/board")
      .then(result => { if (active) setBoard(result); })
      .catch(() => { if (active) toast.error("质检数据加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    request.get<DatasetSnapshot[]>("/api/ml/dataset/snapshots")
      .then(result => { if (active) setSnapshots(result); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const filter = useMemo(() => ({ semester, trainableOnly }), [semester, trainableOnly]);
  const taskIds = useMemo(() => (board?.status === "ok" ? filterTasks(board, filter) : []), [board, filter]);
  const taskIdSet = useMemo(() => new Set(taskIds), [taskIds]);
  const placements = useMemo(
    () => (board?.status === "ok" ? filterPlacements(board, taskIdSet) : []),
    [board, taskIdSet],
  );

  async function capture() {
    setCapturing(true);
    try {
      const snapshot = await request.post<DatasetSnapshot>("/api/ml/dataset/snapshots");
      setSnapshots(current => (current.some(item => item.id === snapshot.id) ? current : [snapshot, ...current]));
      toast.success(`快照已记录 · 指纹 ${snapshot.fingerprint}`);
    } catch {
      toast.error("快照采集失败");
    } finally {
      setCapturing(false);
    }
  }

  if (loading) return <div className="p-8 text-sm text-base-content/50">正在加载质检数据…</div>;

  if (!board || board.status !== "ok") {
    return (
      <Panel title="数据集不可读" description="质检台读取的是 ingest 三步处理的产物，它不进数据库，需要挂载给 ml-api。">
        <p className="text-sm text-base-content/70">{board?.message ?? "未能取到数据集。"}</p>
        {board?.missing?.length ? (
          <p className="mt-2 text-xs text-base-content/50">缺少：{board.missing.join("、")}</p>
        ) : null}
        <p className="mt-3 text-xs text-base-content/50">
          期望目录：<code className="font-mono">{board?.dataset_dir}</code>
        </p>
      </Panel>
    );
  }

  const meta = board.meta;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3 border border-base-300 bg-base-100 px-4 py-3">
        <div className="flex gap-1">
          {VIEWS.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => { setView(item.id); setSearch(""); }}
              className={`btn btn-xs ${view === item.id ? "btn-primary" : "btn-ghost"}`}
            >
              <span className="font-mono text-[10px] opacity-60">{item.no}</span>{item.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <select
            className="select select-bordered select-xs"
            value={semester}
            onChange={event => { setSemester(Number(event.target.value)); setSelectedClass(null); setSelectedRoom(null); }}
          >
            <option value={-1}>全部学期</option>
            {meta.semesters.map((name, index) => (
              <option key={name} value={index}>{name.replace("总课表", "")}</option>
            ))}
          </select>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs">
            <input type="checkbox" className="checkbox checkbox-xs" checked={trainableOnly}
              onChange={event => setTrainableOnly(event.target.checked)} />
            只看可训练
          </label>
          {SEARCHABLE[view] ? (
            <input
              type="search"
              className="input input-bordered input-xs w-44"
              placeholder={`搜索${SEARCHABLE[view]}名称`}
              value={search}
              onChange={event => setSearch(event.target.value)}
            />
          ) : null}
        </div>
      </div>

      {view === "overview" ? <OverviewView board={board} snapshots={snapshots} capturing={capturing} onCapture={capture} /> : null}
      {view === "slots" ? <SlotsView placements={placements} /> : null}
      {view === "classes" ? (
        <ClassesView board={board} taskIds={taskIds} search={search}
          selected={selectedClass} onSelect={setSelectedClass} week={week} onWeek={setWeek} />
      ) : null}
      {view === "rooms" ? (
        <RoomsView board={board} placements={placements} search={search}
          selected={selectedRoom} onSelect={setSelectedRoom} />
      ) : null}
      {view === "courses" ? <CoursesView board={board} taskIds={taskIds} search={search} /> : null}
      {view === "joint" ? <JointView board={board} taskIds={taskIds} /> : null}
    </div>
  );
}

function OverviewView({ board, snapshots, capturing, onCapture }: {
  board: DatasetBoard; snapshots: DatasetSnapshot[]; capturing: boolean; onCapture: () => void;
}) {
  const meta = board.meta;
  const excludedEntries = Object.entries(meta.excluded);
  const maxExcluded = Math.max(1, ...excludedEntries.map(([, value]) => value));
  const excludedTotal = excludedEntries.reduce((sum, [, value]) => sum + value, 0);

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="清洗流水"
        description={`合班课在每个参与班的课表里各出现一次。${formatCount(meta.duplicates_removed)} 行（${((meta.duplicates_removed / meta.occurrence_rows) * 100).toFixed(1)}%）是同一次授课的重复记录，合并后才是真实的授课事件。`}
      >
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <Metric label="源文件" value={formatCount(meta.source_files)} detail="份班级课表 Excel" />
          <Metric label="分班占位行" value={formatCount(meta.occurrence_rows)} detail="一个班一行，含重复" />
          <Metric label="重复剔除" value={`−${formatCount(meta.duplicates_removed)}`} detail="同一次课被记 N 遍" tone="warn" />
          <Metric label="授课事件" value={formatCount(meta.sessions)} detail="物理上真实发生的课" />
          <Metric label="教学任务" value={formatCount(meta.tasks)} detail="一门课 × 一组班级" tone="accent" />
        </div>
      </Panel>

      <Panel title="按学期" description="各学期规模接近，可以按学期做无泄漏的 train/validation/test 切分。">
        <div className="overflow-x-auto">
          <table className="table table-xs">
            <thead><tr><th>学期</th><th className="text-right">教学任务</th><th className="text-right">可训练</th><th className="text-right">合班</th><th className="text-right">授课次数</th></tr></thead>
            <tbody>
              {Object.entries(meta.per_semester).map(([name, row]) => (
                <tr key={name}>
                  <td>{name.replace("总课表", "")}</td>
                  <td className="text-right tabular-nums">{formatCount(row.tasks)}</td>
                  <td className="text-right tabular-nums">{formatCount(row.trainable)}</td>
                  <td className="text-right tabular-nums">
                    {formatCount(row.joint)} <span className="badge badge-ghost badge-xs">{((row.joint / row.tasks) * 100).toFixed(0)}%</span>
                  </td>
                  <td className="text-right tabular-nums">{formatCount(row.sessions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="范围之外" description="按「普通课 + 规律实验课」的口径排除，理由逐条写明。">
          <div className="flex flex-col gap-2">
            {excludedEntries.map(([reason, count]) => (
              <Bar key={reason} label={reason} value={count} max={maxExcluded} tone="warn" />
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-base-content/55">
            共排除 <strong className="text-base-content/80">{formatCount(excludedTotal)}</strong> 个任务，
            保留 <strong className="text-base-content/80">{formatCount(meta.trainable.tasks)}</strong> 个。
            排除不是删除——每条记录都留在数据里带着 <code className="font-mono">untrainable_reason</code>，随时可以放回来。
          </p>
        </Panel>

        <Panel title="已知问题" description="标出来的问题比看不见的问题便宜。">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Metric label="教师名冲突" value={formatCount(meta.quality.teacher_name_conflict_sessions)} detail="次授课在不同班课表里记了不同教师" />
            <Metric label="缺班级人数" value={formatCount(meta.quality.tasks_missing_student_count)} detail="个任务算不出合班总人数" />
            <Metric label="跨教室任务" value={formatCount(meta.quality.tasks_using_multiple_rooms)} detail="个任务用到多间教室" />
          </div>
          <p className="mt-3 text-xs leading-relaxed text-base-content/55">
            这三项都是<strong className="text-base-content/80">已标记、未处理</strong>的已知问题，不是隐藏的错误。
            跨教室经抽查是合法的：同一门课理论在普通教室、上机在机房。
          </p>
        </Panel>
      </div>

      <Panel
        title="质检快照"
        description="清洗规则一改，可训练任务数和排除分布都会变。指纹取自结果内容，同口径重复采集不会新增行。"
      >
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn btn-primary btn-xs" onClick={onCapture} disabled={capturing}>
            {capturing ? "采集中…" : "采集当前快照"}
          </button>
          <span className="font-mono text-xs text-base-content/50">当前指纹 {board.fingerprint}</span>
        </div>
        {snapshots.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="table table-xs">
              <thead><tr><th>时间</th><th>指纹</th><th className="text-right">教学任务</th><th className="text-right">可训练</th><th className="text-right">合班</th><th className="text-right">晚间授课</th><th>采集人</th></tr></thead>
              <tbody>
                {snapshots.map(item => (
                  <tr key={item.id} className={item.fingerprint === board.fingerprint ? "bg-primary/10" : undefined}>
                    <td className="tabular-nums">{item.createdAt?.replace("T", " ").slice(0, 16)}</td>
                    <td className="font-mono text-xs">{item.fingerprint}</td>
                    <td className="text-right tabular-nums">{formatCount(item.teachingTasks)}</td>
                    <td className="text-right tabular-nums">{formatCount(item.trainableTasks)}</td>
                    <td className="text-right tabular-nums">{formatCount(item.jointTasks)}</td>
                    <td className="text-right tabular-nums">{formatCount(item.eveningSessions)}</td>
                    <td className="text-xs text-base-content/55">{item.capturedBy ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-xs text-base-content/50">还没有快照。采集一次后，之后每次调整清洗规则都能和它对比。</p>
        )}
      </Panel>
    </div>
  );
}

function SlotsView({ placements }: { placements: PlacementRow[] }) {
  const { grid, max, total } = useMemo(() => slotGrid(placements), [placements]);
  let weekdayDaytime = 0;
  let evening = 0;
  let weekend = 0;
  for (let period = 1; period <= 11; period += 1) {
    for (let day = 1; day <= 7; day += 1) {
      const value = grid[period][day];
      if (day >= 6) weekend += value;
      if (period >= 9) evening += value;
      if (day <= 5 && period <= 8) weekdayDaytime += value;
    }
  }
  const share = (value: number) => (total ? ((value / total) * 100).toFixed(1) : "0.0");

  return (
    <Panel
      title="时段热力图"
      description="按星期 × 45 分钟原子节次统计授课次数，已按周次展开。续占节次不重复计数——连 4 节的实验课算一次课，不是四次。"
    >
      <HeatTable grid={grid} max={max} unit="次授课" />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-base-content/55">
        <span>少</span>
        {HEAT_LEGEND.map(cls => <span key={cls} className={`inline-block h-3 w-6 ${cls}`} />)}
        <span>多 · 峰值 {formatCount(max)} 次 · 合计 {formatCount(total)} 次</span>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Metric label="工作日 1–8 节" value={`${share(weekdayDaytime)}%`} detail={`${formatCount(weekdayDaytime)} 次 · 自动排课域`} tone="accent" />
        <Metric label="晚间 9–11 节" value={`${share(evening)}%`} detail={`${formatCount(evening)} 次 · 人工保留域`} tone="warn" />
        <Metric label="周末" value={`${share(weekend)}%`} detail={`${formatCount(weekend)} 次 · 人工保留域`} tone="warn" />
      </div>
      <p className="mt-3 max-w-4xl text-xs leading-relaxed text-base-content/55">
        这张图是最快的体检：<strong className="text-base-content/80">工作日 1–8 节应当密集，晚间和周末应当稀疏但不为零</strong>。
        晚间不为零，说明带 <code className="font-mono">(9-10)</code> 标注的晚课没有被解析器吃掉；
        周末接近零，说明没有把人工保留时段当成常规排课域。
      </p>
    </Panel>
  );
}

function ClassesView({ board, taskIds, search, selected, onSelect, week, onWeek }: {
  board: DatasetBoard; taskIds: number[]; search: string;
  selected: number | null; onSelect: (value: number) => void;
  week: number; onWeek: (value: number) => void;
}) {
  const byClass = useMemo(() => {
    const map = new Map<number, number[]>();
    taskIds.forEach(id => {
      board.tasks[id][T.CLASSES].forEach(classId => {
        const list = map.get(classId);
        if (list) list.push(id); else map.set(classId, [id]);
      });
    });
    return map;
  }, [board, taskIds]);

  const names = useMemo(() => {
    const list = [...byClass.keys()];
    const filtered = search ? list.filter(id => board.classes[id].includes(search)) : list;
    return filtered.sort((a, b) => board.classes[a].localeCompare(board.classes[b], "zh"));
  }, [byClass, board, search]);

  const active = selected != null && byClass.has(selected) ? selected : names[0];
  if (active == null) return <Panel title="班级课表"><p className="text-sm text-base-content/50">没有匹配的班级。</p></Panel>;

  const tasks = byClass.get(active) ?? [];
  const taskSet = new Set(tasks);
  const rows = board.placements.filter(row => taskSet.has(row[P.TASK]));
  const unionMask = rows.reduce((mask, row) => mask | row[P.MASK], 0);
  const weeks = weeksOf(unionMask);
  const activeWeek = weeks.includes(week) ? week : (weeks[0] ?? 1);

  const cells = new Map<string, { row: PlacementRow; continued: boolean }>();
  rows.forEach(row => {
    if (!hasWeek(row[P.MASK], activeWeek)) return;
    for (let offset = 0; offset < row[P.SPAN]; offset += 1) {
      cells.set(`${row[P.DAY]}-${row[P.PERIOD] + offset}`, { row, continued: offset > 0 });
    }
  });

  return (
    <div className="flex flex-col gap-4">
      <Panel title="选择班级" description={`当前筛选下有 ${formatCount(names.length)} 个班级。`}>
        <div className="flex flex-wrap gap-1.5">
          {names.slice(0, 60).map(id => (
            <button key={id} type="button" onClick={() => onSelect(id)}
              className={`btn btn-xs ${id === active ? "btn-primary" : "btn-outline"}`}>
              {board.classes[id]}
            </button>
          ))}
        </div>
        {names.length > 60 ? <p className="mt-2 text-xs text-base-content/50">共 {formatCount(names.length)} 个班级，这里显示前 60 个，用上方搜索缩小范围。</p> : null}
      </Panel>

      <Panel
        title={`${board.classes[active]} · 第${activeWeek}周课表`}
        description="按周次展开的真实课表。把这张表和学校发的原始课表逐格对照，是最直接的验证。"
      >
        <div className="flex flex-wrap gap-1">
          {weeks.map(value => (
            <button key={value} type="button" onClick={() => onWeek(value)}
              className={`btn btn-xs ${value === activeWeek ? "btn-primary" : "btn-ghost"}`}>第{value}周</button>
          ))}
        </div>
        <div className="mt-3 overflow-x-auto">
          <div className="grid min-w-[52rem] grid-cols-[5.5rem_repeat(7,minmax(7rem,1fr))] gap-[3px]">
            <div />
            {DAY_LABELS.map(day => <div key={day} className="py-1 text-center text-xs font-medium text-base-content/55">{day}</div>)}
            {ALL_PERIODS.map(period => (
              <ClassPeriodRow key={period} board={board} period={period} cells={cells} />
            ))}
          </div>
        </div>
        <p className="mt-3 max-w-4xl text-xs leading-relaxed text-base-content/55">
          一节 45 分钟。<strong className="text-base-content/80">↳ 是续占节次</strong>——理论课连 2 节、上机课连 4 节，
          起始节次记课程，后续节次标续占。合班的格子写明参与班数与总人数。
        </p>
      </Panel>

      <Panel title="该班级的教学任务" description={`${formatCount(tasks.length)} 个任务。合班任务同时出现在其他班的课表里，但只算一次授课。`}>
        <div className="overflow-x-auto">
          <table className="table table-xs">
            <thead><tr><th>课程</th><th>代码</th><th>教师</th><th>班型</th><th className="text-right">授课次数</th><th className="text-right">课时</th><th className="text-right">覆盖周</th><th>范围</th></tr></thead>
            <tbody>
              {tasks.map(id => {
                const task = board.tasks[id];
                return (
                  <tr key={id}>
                    <td>{board.courses[task[T.COURSE]]}</td>
                    <td className="font-mono text-xs">{task[T.CODE]}</td>
                    <td>{task[T.TEACHERS].map(t => board.teachers[t]).join("、") || "—"}</td>
                    <td>{task[T.JOINT]
                      ? <span className="badge badge-warning badge-xs">合班 {task[T.CLASSES].length}</span>
                      : <span className="badge badge-ghost badge-xs">单班</span>}</td>
                    <td className="text-right tabular-nums">{formatCount(task[T.SESSIONS])}</td>
                    <td className="text-right tabular-nums">{formatCount(task[T.PERIODS])}</td>
                    <td className="text-right tabular-nums">{formatCount(task[T.WEEKS])}</td>
                    <td>{task[T.TRAINABLE]
                      ? <span className="badge badge-success badge-xs">可训练</span>
                      : <span className="badge badge-warning badge-xs" title={board.reasons[task[T.REASON]]}>排除</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function ClassPeriodRow({ board, period, cells }: {
  board: DatasetBoard; period: number; cells: Map<string, { row: PlacementRow; continued: boolean }>;
}) {
  return (
    <>
      <div className="flex flex-col justify-center text-xs text-base-content/70">
        第{period}节<span className="text-[10px] text-base-content/40">{periodDetailLabel(period)}</span>
      </div>
      {DAY_LABELS.map((day, index) => {
        const hit = cells.get(`${index + 1}-${period}`);
        if (!hit) return <div key={day} className="min-h-[2.9rem] bg-base-200" />;
        const task = board.tasks[hit.row[P.TASK]];
        return (
          <div key={day} className={`min-h-[2.9rem] border border-primary/25 bg-primary/10 p-1.5 text-[11px] leading-tight ${hit.continued ? "opacity-70" : ""}`}>
            <div className="font-medium text-primary">{hit.continued ? "↳ " : ""}{board.courses[task[T.COURSE]]}</div>
            <div className="mt-0.5 font-mono text-[10px] text-base-content/55">
              {board.rooms[hit.row[P.ROOM]]}{hit.continued ? "" : ` · 连${hit.row[P.SPAN]}节`}
            </div>
            {hit.continued ? null : (
              <>
                <div className="text-[10px] text-base-content/55">{task[T.TEACHERS].map(t => board.teachers[t]).join("、") || "—"}</div>
                {task[T.JOINT] ? (
                  <div className="text-[10px] text-warning">合班 {task[T.CLASSES].length} 个班 · {task[T.STUDENTS] || "?"}人</div>
                ) : null}
              </>
            )}
          </div>
        );
      })}
    </>
  );
}

function RoomsView({ board, placements, search, selected, onSelect }: {
  board: DatasetBoard; placements: PlacementRow[]; search: string;
  selected: number | null; onSelect: (value: number) => void;
}) {
  const ranked = useMemo(() => {
    const map = new Map<number, { sessions: number; periods: number; tasks: Set<number> }>();
    placements.forEach(row => {
      const times = weekCount(row[P.MASK]);
      const entry = map.get(row[P.ROOM]) ?? { sessions: 0, periods: 0, tasks: new Set<number>() };
      entry.sessions += times;
      entry.periods += times * row[P.SPAN];
      entry.tasks.add(row[P.TASK]);
      map.set(row[P.ROOM], entry);
    });
    const list = [...map.entries()];
    const filtered = search ? list.filter(([id]) => board.rooms[id].includes(search)) : list;
    return filtered.sort((a, b) => b[1].periods - a[1].periods);
  }, [placements, board, search]);

  if (!ranked.length) return <Panel title="教室占用"><p className="text-sm text-base-content/50">没有匹配的教室。</p></Panel>;
  const active = selected != null && ranked.some(([id]) => id === selected) ? selected : ranked[0][0];
  const { grid, max } = roomGrid(placements.filter(row => row[P.ROOM] === active));

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="教室占用排行"
        description={`共 ${formatCount(ranked.length)} 间教室。占用率以 18 周 × 工作日 × 第 1–8 节（${formatCount(WEEKDAY_DAYTIME_CAPACITY)} 节）为分母，超过 100% 说明用到了晚间或周末。点一行看它的周占用。`}
      >
        <div className="max-h-96 overflow-auto">
          <table className="table table-xs table-pin-rows">
            <thead><tr><th>教室</th><th className="text-right">授课次数</th><th className="text-right">占用课时</th><th className="text-right">教学任务</th><th className="text-right">占用率</th></tr></thead>
            <tbody>
              {ranked.slice(0, 80).map(([id, stat]) => (
                <tr key={id} onClick={() => onSelect(id)}
                  className={`cursor-pointer ${id === active ? "bg-primary/10" : ""}`}>
                  <td className="font-mono">{board.rooms[id]}</td>
                  <td className="text-right tabular-nums">{formatCount(stat.sessions)}</td>
                  <td className="text-right tabular-nums">{formatCount(stat.periods)}</td>
                  <td className="text-right tabular-nums">{formatCount(stat.tasks.size)}</td>
                  <td className="text-right tabular-nums">{((stat.periods / WEEKDAY_DAYTIME_CAPACITY) * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={`教室 ${board.rooms[active]} · 周占用`} description="格子里是该时段被占用的周数。同一间教室同一时段不可能超过 18 周——超了说明还原时把两次课并错了。">
        <HeatTable grid={grid} max={max} unit="周占用" />
      </Panel>
    </div>
  );
}

function CoursesView({ board, taskIds, search }: { board: DatasetBoard; taskIds: number[]; search: string }) {
  const ranked = useMemo(() => {
    const map = new Map<number, { tasks: number; joint: number; sessions: number; periods: number; trainable: number; code: string; type: string }>();
    taskIds.forEach(id => {
      const task = board.tasks[id];
      const entry = map.get(task[T.COURSE]) ?? { tasks: 0, joint: 0, sessions: 0, periods: 0, trainable: 0, code: task[T.CODE], type: task[T.TYPE] };
      entry.tasks += 1;
      entry.sessions += task[T.SESSIONS];
      entry.periods += task[T.PERIODS];
      if (task[T.JOINT]) entry.joint += 1;
      if (task[T.TRAINABLE]) entry.trainable += 1;
      map.set(task[T.COURSE], entry);
    });
    const list = [...map.entries()];
    const filtered = search ? list.filter(([id]) => board.courses[id].includes(search)) : list;
    return filtered.sort((a, b) => b[1].periods - a[1].periods);
  }, [board, taskIds, search]);

  return (
    <Panel
      title="课程与教学任务"
      description={`${formatCount(ranked.length)} 门课程，按占用课时排序，显示前 ${Math.min(120, ranked.length)} 门。一门课程可以对应多个教学任务——不同班级组合就是不同任务。`}
    >
      <div className="max-h-[38rem] overflow-auto">
        <table className="table table-xs table-pin-rows">
          <thead><tr><th>课程</th><th>代码</th><th>类型</th><th className="text-right">教学任务</th><th className="text-right">其中合班</th><th className="text-right">授课次数</th><th className="text-right">课时</th><th>可训练</th></tr></thead>
          <tbody>
            {ranked.slice(0, 120).map(([id, stat]) => (
              <tr key={id}>
                <td>{board.courses[id]}</td>
                <td className="font-mono text-xs">{stat.code}</td>
                <td>{stat.type === "上机课"
                  ? <span className="badge badge-primary badge-xs">上机/实验</span>
                  : <span className="badge badge-ghost badge-xs">理论</span>}</td>
                <td className="text-right tabular-nums">{formatCount(stat.tasks)}</td>
                <td className="text-right tabular-nums">
                  {stat.joint ? <>{formatCount(stat.joint)} <span className="badge badge-warning badge-xs">{((stat.joint / stat.tasks) * 100).toFixed(0)}%</span></> : "—"}
                </td>
                <td className="text-right tabular-nums">{formatCount(stat.sessions)}</td>
                <td className="text-right tabular-nums">{formatCount(stat.periods)}</td>
                <td>{stat.trainable === stat.tasks
                  ? <span className="badge badge-success badge-xs">全部</span>
                  : <span className="badge badge-warning badge-xs">{stat.trainable}/{stat.tasks}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function JointView({ board, taskIds }: { board: DatasetBoard; taskIds: number[] }) {
  const dist = useMemo(() => {
    const map = new Map<number, number>();
    taskIds.forEach(id => {
      const size = board.tasks[id][T.CLASSES].length;
      map.set(size, (map.get(size) ?? 0) + 1);
    });
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [board, taskIds]);
  const maxDist = Math.max(1, ...dist.map(([, value]) => value));
  const jointCount = taskIds.filter(id => board.tasks[id][T.JOINT]).length;

  const detail = useMemo(() => taskIds
    .filter(id => board.tasks[id][T.JOINT])
    .sort((a, b) => board.tasks[b][T.CLASSES].length - board.tasks[a][T.CLASSES].length
      || board.tasks[b][T.PERIODS] - board.tasks[a][T.PERIODS])
    .slice(0, 60), [board, taskIds]);

  return (
    <div className="flex flex-col gap-4">
      <Panel title="合班分布" description="合班是推断结果，不是数据里读来的字段。">
        <div className="flex flex-col gap-2">
          {dist.map(([size, count]) => (
            <Bar key={size} label={size === 1 ? "单班" : `合班 · ${size} 个班`} value={count} max={maxDist} tone={size === 1 ? "mute" : undefined} />
          ))}
        </div>
        <p className="mt-3 max-w-4xl text-xs leading-relaxed text-base-content/55">
          当前筛选下 <strong className="text-base-content/80">{formatCount(jointCount)}</strong> / {formatCount(taskIds.length)} 个任务是合班
          （{taskIds.length ? ((jointCount / taskIds.length) * 100).toFixed(1) : "0.0"}%）。原始课表里
          <strong className="text-base-content/80">没有任何"合班"标注</strong>——这是从「同学期 + 同课程 + 同教室 + 同周同星期同节次」
          的重合关系推出来的：物理上同一时刻同一间教室只可能上一门课。
        </p>
      </Panel>

      <Panel
        title="合班任务明细"
        description="按参与班数排序。总人数是各班之和——合班要的教室得装得下所有人，这是排课容量约束的正确口径；带 ? 的是有班级缺人数、不猜的。"
      >
        <div className="max-h-[34rem] overflow-auto">
          <table className="table table-xs table-pin-rows">
            <thead><tr><th>课程</th><th>参与班级</th><th className="text-right">班数</th><th className="text-right">总人数</th><th>教师</th><th className="text-right">授课次数</th><th className="text-right">课时</th></tr></thead>
            <tbody>
              {detail.map(id => {
                const task = board.tasks[id];
                return (
                  <tr key={id}>
                    <td>{board.courses[task[T.COURSE]]}</td>
                    <td className="max-w-md truncate" title={task[T.CLASSES].map(c => board.classes[c]).join("、")}>
                      {task[T.CLASSES].map(c => board.classes[c]).join("、")}
                    </td>
                    <td className="text-right"><span className="badge badge-warning badge-xs">{task[T.CLASSES].length}</span></td>
                    <td className="text-right tabular-nums">
                      {task[T.STUDENTS_OK] ? formatCount(task[T.STUDENTS])
                        : <span className="text-error" title="有班级缺人数">{formatCount(task[T.STUDENTS])}?</span>}
                    </td>
                    <td>{task[T.TEACHERS].map(t => board.teachers[t]).join("、") || "—"}</td>
                    <td className="text-right tabular-nums">{formatCount(task[T.SESSIONS])}</td>
                    <td className="text-right tabular-nums">{formatCount(task[T.PERIODS])}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
