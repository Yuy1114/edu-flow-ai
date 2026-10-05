import { useState, useEffect, useRef } from "react";
import request from "../api/request";
import { toast } from "sonner";
import { ALL_PERIODS, DEFAULT_ALLOWED_PERIODS } from "../lib/schedulingTime";

interface AllocationTask { id: number; name: string; generationConfig?: any; schemeCount?: number; status: string; teachingTasks?: { id: number }[]; }
export interface GenerationStatus {
  status: "IDLE" | "RUNNING" | "SUCCESS" | "NEEDS_MANUAL_REVIEW" | "BLOCKED" | "FAILED";
  startedAt?: number;
  finishedAt?: number;
  progress?: number;
  error?: string;
  jobId?: string;
}
export interface AllocationScheme {
  id: number;
  taskId: number;
  allocationTaskId?: number;
  schemeName?: string;
  name?: string;
  status: string;
  createdAt?: string;
  schemeScore?: number;
  valid?: boolean;
  modelVersion?: string;
  summary?: string;
  conflictSummary?: string;
}
export interface SchemeItem {
  id: number;
  templateFragmentId?: number;
  templateId?: number;
  fragmentCode?: string;
  schemeId: number;
  teachingTaskId: number;
  courseName: string;
  teacherName: string;
  classGroupName: string;
  classroomId: number;
  classroomName: string;
  timeSlotId: number;
  timeSlotLabel: string;
  weekNumber: number;
  dayOfWeek: number;
  periodIndex: number;
  teacherProfileScore?: number;
  teacherProfilePenalty?: number;
  valid: boolean;
  conflictMessage?: string;
  consecutiveSlots?: number;
  durationWeeks?: number;
  weekNumbers?: number[];
  sourceType?: string;
}

export interface TemplateTaskHourAudit {
  teachingTaskId: number;
  courseName: string;
  requiredHours: number;
  scheduledHours: number;
  deltaHours: number;
  sessionPeriods: number;
  status: "OK" | "UNDER" | "OVER";
}

export interface TeacherSatisfactionEntry {
  templateCode: string;
  teacherKey: string;
  teacherId: number | null;
  teacherName: string;
  itemCount: number;
  daysUsed: number;
  satisfactionScore: number;
  preferenceScore: number;
  lowSatisfaction: boolean;
  declaredDimensions: string[];
  primaryReasonDimension: string | null;
  primaryReasonScore: number | null;
  components: Record<string, number>;
  evidence: Record<string, number | null>;
}

export interface TeacherSatisfactionView {
  profileApplied: boolean;
  teacherCount: number;
  averageSatisfactionScore: number;
  averagePreferenceScore: number;
  lowSatisfactionCount: number;
  teachers: TeacherSatisfactionEntry[];
  lowSatisfactionTeachers: TeacherSatisfactionEntry[];
}

export interface TemplateDraftView {
  schemeId: number;
  allocationTaskId: number;
  generationRunId: string;
  templates: { id: number; templateCode: string; templateName: string; fragmentCount: number; taskCount: number; weekNumbers: number[] }[];
  audit: {
    reviewStatus: "COMPLETE" | "COMPLETE_WITH_EXCEPTION" | "NEEDS_MANUAL_REVIEW" | "BLOCKED";
    valid: boolean;
    hardConflictCount: number;
    teacherConflictCount: number;
    classGroupConflictCount: number;
    classroomConflictCount: number;
    capacityMismatchCount: number;
    roomTypeMismatchCount: number;
    identityIssueCount: number;
    hourMismatchTaskCount: number;
    requiredTotalHours: number;
    scheduledTotalHours: number;
    deltaTotalHours: number;
    taskHours: TemplateTaskHourAudit[];
    issues: string[];
  };
  /** 画像未参与本次生成时该块整体不出现，页面据此隐藏整段。 */
  satisfaction?: TeacherSatisfactionView | null;
}

interface TeachingTaskBrief {
  id: number;
  courseName: string;
  teacherName: string;
  classGroupNames: string;
  taskBatch: string;
}

const WEEKS = Array.from({length: 18}, (_, i) => i + 1);
const WEEKDAYS = [{l:"周一",v:1},{l:"周二",v:2},{l:"周三",v:3},{l:"周四",v:4},{l:"周五",v:5},{l:"周六",v:6},{l:"周日",v:7}];
const PERIODS = ALL_PERIODS;

const defaultConfig = () => ({
  allowedWeeks: "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18",
  allowedWeekdays: "1,2,3,4,5",
  allowedPeriods: DEFAULT_ALLOWED_PERIODS,
  schemeCount: 3, generationMode: "AUTO", placementTopK: 80, rawPlanCount: 240, cpPlanCount: 80,
  solverTimeLimitSeconds: 3600, teacherProfilePenaltyScale: 80, earlyPeriodPenalty: 0.04, latePeriodPenalty: 0.03,
  weekendPenalty: 0.05, modelWeight: 0.6, llmWeight: 0.4, sameDayWeight: 0.05,
  capacityWastePenalty: 0, teacherDayLoadPenalty: 0, classDayLoadPenalty: 0, teacherOverloadPenalty: 0,
});

export function useAllocation() {
  const [tasks, setTasks] = useState<AllocationTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskDialog, setTaskDialog] = useState(false);
  const [taskForm, setTaskForm] = useState({ id: null as number|null, name: "", teachingTaskIds: [] as number[], generationConfig: defaultConfig() });
  const [saving, setSaving] = useState(false);
  const [selectedTask, setSelectedTask] = useState<AllocationTask | null>(null);
  const [schemes, setSchemes] = useState<AllocationScheme[]>([]);
  const [schemesLoading, setSchemesLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generateStatus, setGenerateStatus] = useState("");
  const [generateProgress, setGenerateProgress] = useState(0);
  const [generationError, setGenerationError] = useState("");
  const [lastGeneration, setLastGeneration] = useState<GenerationStatus | null>(null);
  const selectedTaskIdRef = useRef<number | null>(null);
  const selectionEpochRef = useRef(0);
  const pollEpochRef = useRef(0);
  const mountedRef = useRef(true);

  // Scheme detail
  const [detailScheme, setDetailScheme] = useState<AllocationScheme | null>(null);
  const [schemeItems, setSchemeItems] = useState<SchemeItem[]>([]);
  const [schemeItemsLoading, setSchemeItemsLoading] = useState(false);

  // Teaching task briefs (for task dialog selector)
  const [teachingTasks, setTeachingTasks] = useState<TeachingTaskBrief[]>([]);
  const [teachingTasksLoading, setTeachingTasksLoading] = useState(false);
  const [teachingTaskBatchFilter, setTeachingTaskBatchFilter] = useState("");

  // V3.5 template state
  const [v35Templates, setV35Templates] = useState<any[]>([]);
  const [v35TemplateWeeks, setV35TemplateWeeks] = useState<any[]>([]);
  const [v35WeekTimetable, setV35WeekTimetable] = useState<any[]>([]);
  const [v35SelectedWeek, setV35SelectedWeek] = useState<number | null>(null);
  const [v35TemplatesLoading, setV35TemplatesLoading] = useState(false);

  useEffect(() => {
    mountedRef.current = true;
    void loadTasks(true);
    return () => {
      mountedRef.current = false;
      pollEpochRef.current += 1;
    };
  }, []);

  async function loadTasks(restoreSelection = false) {
    setLoading(true);
    try {
      const data = await request.get<AllocationTask[]>("/api/allocation-tasks");
      const rows = Array.isArray(data) ? data : [];
      if (!mountedRef.current) return;
      setTasks(rows);
      if (restoreSelection && selectedTaskIdRef.current == null) {
        let storedTaskId = 0;
        try { storedTaskId = Number(sessionStorage.getItem("edu-flow-selected-allocation-task")); } catch { /* storage unavailable */ }
        const taskToRestore = rows.find(task => task.id === storedTaskId)
          ?? rows.find(task => task.status === "RUNNING");
        if (taskToRestore) void selectTask(taskToRestore);
      }
    } catch {
      if (mountedRef.current) setTasks([]);
    }
    finally { if (mountedRef.current) setLoading(false); }
  }

  async function loadTeachingTasks() {
    setTeachingTasksLoading(true);
    try {
      const raw: any = await request.get("/api/teaching-tasks");
      const list: any[] = Array.isArray(raw) ? raw : raw?.content ?? [];
      setTeachingTasks(list.map(t => ({
        id: t.id,
        courseName: t.course?.name || `课程#${t.courseId}`,
        teacherName: t.primaryTeacher?.name || "",
        classGroupNames: t.classGroups?.map((cg: any) => cg.name).join(", ") || "",
        taskBatch: t.taskBatch || "DEFAULT",
      })));
    } catch { setTeachingTasks([]); }
    finally { setTeachingTasksLoading(false); }
  }

  const filteredTeachingTasks = !teachingTaskBatchFilter
    ? teachingTasks
    : teachingTasks.filter(tt => tt.taskBatch === teachingTaskBatchFilter);

  const teachingTaskBatchOptions = [...new Set(teachingTasks.map(tt => tt.taskBatch))].sort();

  async function openTaskDialog(row?: AllocationTask) {
    if (row) {
      const teachingTaskIds = row.teachingTasks?.map(tt => tt.id) ?? [];
      setTaskForm({ id: row.id, name: row.name, teachingTaskIds, generationConfig: row.generationConfig || defaultConfig() });
      try {
        const detail: AllocationTask = await request.get(`/api/allocation-tasks/${row.id}`);
        setTaskForm({
          id: detail.id,
          name: detail.name,
          teachingTaskIds: detail.teachingTasks?.map(tt => tt.id) ?? teachingTaskIds,
          generationConfig: detail.generationConfig || row.generationConfig || defaultConfig(),
        });
      } catch {
        // 保留列表行数据，避免编辑入口直接失败
      }
    } else {
      setTaskForm({ id: null, name: "", teachingTaskIds: [], generationConfig: defaultConfig() });
    }
    loadTeachingTasks();
    setTaskDialog(true);
  }

  function serializeConfig(cfg: any) {
    const serialized = { ...cfg };
    if (Array.isArray(serialized.allowedWeeks)) serialized.allowedWeeks = serialized.allowedWeeks.join(",");
    if (Array.isArray(serialized.allowedWeekdays)) serialized.allowedWeekdays = serialized.allowedWeekdays.join(",");
    if (Array.isArray(serialized.allowedPeriods)) serialized.allowedPeriods = serialized.allowedPeriods.join(",");
    return serialized;
  }

  async function saveTask() {
    setSaving(true);
    try {
      const body = {
        ...taskForm,
        generationConfig: taskForm.generationConfig ? serializeConfig(taskForm.generationConfig) : taskForm.generationConfig,
      };
      if (taskForm.id) await request.put(`/api/allocation-tasks/${taskForm.id}`, body);
      else await request.post("/api/allocation-tasks", body);
      toast.success("保存成功");
      setTaskDialog(false);
      loadTasks();
    } catch { toast.error("保存失败"); }
    finally { setSaving(false); }
  }

  async function deleteTask(id: number) {
    if (!confirm("确认删除该排课任务？")) return;
    try { await request.delete(`/api/allocation-tasks/${id}`); toast.success("已删除"); loadTasks(); }
    catch { toast.error("删除失败"); }
  }

  function clearV35State() {
    setV35Templates([]);
    setV35TemplateWeeks([]);
    setV35WeekTimetable([]);
    setV35SelectedWeek(null);
    setV35TemplatesLoading(false);
    setLastGeneration(null);
    setGenerationError("");
    setGenerating(false);
    setGenerateProgress(0);
    setGenerateStatus("");
  }

  function isCurrentSelection(taskId: number, selectionEpoch: number) {
    return mountedRef.current
      && selectedTaskIdRef.current === taskId
      && selectionEpochRef.current === selectionEpoch;
  }

  function applyGenerationStatus(taskId: number, selectionEpoch: number, status: GenerationStatus) {
    if (!isCurrentSelection(taskId, selectionEpoch)) return;
    setLastGeneration(status);
    const terminalError = status.status === "BLOCKED" || status.status === "FAILED"
      ? status.error || "排课作业未完成"
      : "";
    setGenerationError(terminalError);
    if (status.status === "RUNNING") {
      setGenerating(true);
      setGenerateStatus("V3.5 排课进行中，请稍候...");
      setGenerateProgress(Math.max(0, Math.min(99, status.progress ?? 0)));
      return;
    }
    setGenerating(false);
    if (status.status === "SUCCESS") {
      setGenerateStatus("排课完成");
      setGenerateProgress(100);
    } else if (status.status === "NEEDS_MANUAL_REVIEW") {
      setGenerateStatus("自动排课完成，等待人工复核");
      setGenerateProgress(100);
    } else if (terminalError) {
      setGenerateStatus("排课未完成，请查看原因并修复输入后重试");
      setGenerateProgress(0);
    } else {
      setGenerateStatus("");
      setGenerateProgress(0);
    }
  }

  async function loadSchemesForTask(taskId: number, selectionEpoch: number) {
    setSchemesLoading(true);
    try {
      const data = await request.get("/api/allocation-schemes", { params: { taskId } });
      if (isCurrentSelection(taskId, selectionEpoch)) {
        setSchemes(Array.isArray(data) ? data : data?.content || []);
      }
    } catch {
      if (isCurrentSelection(taskId, selectionEpoch)) setSchemes([]);
    } finally {
      if (isCurrentSelection(taskId, selectionEpoch)) setSchemesLoading(false);
    }
  }

  async function selectTask(task: AllocationTask) {
    pollEpochRef.current += 1;
    const selectionEpoch = ++selectionEpochRef.current;
    selectedTaskIdRef.current = task.id;
    try { sessionStorage.setItem("edu-flow-selected-allocation-task", String(task.id)); } catch { /* storage unavailable */ }
    setSelectedTask(task);
    setDetailScheme(null);
    setSchemeItems([]);
    clearV35State();
    setSchemes([]);
    void loadSchemesForTask(task.id, selectionEpoch);
    void loadGenerationStatus(task.id, selectionEpoch, true);
  }

  async function loadSchemeItems(scheme: AllocationScheme) {
    setDetailScheme(scheme);
    setSchemeItemsLoading(true);
    try {
      const data = await request.get(`/api/allocation-schemes/${scheme.id}/items`);
      setSchemeItems(Array.isArray(data) ? data : []);
    } catch { setSchemeItems([]); toast.error("加载方案明细失败"); }
    finally { setSchemeItemsLoading(false); }
  }

  async function loadV35Templates(taskId: number, selectionEpoch = selectionEpochRef.current) {
    setV35TemplatesLoading(true);
    try {
      const [templatesData, weeksData] = await Promise.all([
        request.get(`/api/allocation-tasks/${taskId}/templates`),
        request.get(`/api/allocation-tasks/${taskId}/templates/weeks`),
      ]);
      if (isCurrentSelection(taskId, selectionEpoch)) {
        setV35Templates(Array.isArray(templatesData) ? templatesData : []);
        setV35TemplateWeeks(Array.isArray(weeksData) ? weeksData : []);
        setV35WeekTimetable([]);
        setV35SelectedWeek(null);
      }
    } catch {
      if (isCurrentSelection(taskId, selectionEpoch)) {
        setV35Templates([]);
        setV35TemplateWeeks([]);
      }
    } finally {
      if (isCurrentSelection(taskId, selectionEpoch)) setV35TemplatesLoading(false);
    }
  }

  async function loadV35WeekTimetable(taskId: number, weekNumber: number) {
    const selectionEpoch = selectionEpochRef.current;
    try {
      const data = await request.get(`/api/allocation-tasks/${taskId}/templates/weeks/${weekNumber}/timetable`);
      if (isCurrentSelection(taskId, selectionEpoch)) {
        setV35WeekTimetable(Array.isArray(data) ? data : []);
        setV35SelectedWeek(weekNumber);
      }
    } catch {
      if (isCurrentSelection(taskId, selectionEpoch)) setV35WeekTimetable([]);
    }
  }

  async function refreshAfterGeneration(taskId: number, selectionEpoch: number) {
    const detailRequest = request.get<AllocationTask>(`/api/allocation-tasks/${taskId}`).catch(() => null);
    await Promise.all([
      loadTasks(),
      loadSchemesForTask(taskId, selectionEpoch),
      loadV35Templates(taskId, selectionEpoch),
    ]);
    const detail = await detailRequest;
    if (detail && isCurrentSelection(taskId, selectionEpoch)) setSelectedTask(detail);
  }

  async function finishGeneration(
    taskId: number,
    selectionEpoch: number,
    status: GenerationStatus,
    announce: boolean,
  ) {
    applyGenerationStatus(taskId, selectionEpoch, status);
    if (status.status === "SUCCESS" || status.status === "NEEDS_MANUAL_REVIEW") {
      await refreshAfterGeneration(taskId, selectionEpoch);
      if (announce && isCurrentSelection(taskId, selectionEpoch)) {
        if (status.status === "SUCCESS") toast.success("V3.5 模板排课完成");
        else toast.warning(status.error || "已生成待人工复核的候选课表");
      }
    } else if (announce && (status.status === "BLOCKED" || status.status === "FAILED") && isCurrentSelection(taskId, selectionEpoch)) {
      toast.error(status.error || "V3.5 排课失败");
    }
  }

  async function pollGeneration(taskId: number, selectionEpoch: number, announce: boolean) {
    const pollEpoch = ++pollEpochRef.current;
    const pollInterval = 3000;
    const maxPolls = 600; // 30 minutes, aligned with the durable worker timeout.
    for (let index = 0; index < maxPolls; index += 1) {
      if (!isCurrentSelection(taskId, selectionEpoch) || pollEpochRef.current !== pollEpoch) return;
      try {
        const status = await request.get<GenerationStatus>(`/api/allocation-tasks/${taskId}/templates/generation-status`, { suppressErrorToast: true });
        if (!isCurrentSelection(taskId, selectionEpoch) || pollEpochRef.current !== pollEpoch) return;
        applyGenerationStatus(taskId, selectionEpoch, status);
        if (["SUCCESS", "NEEDS_MANUAL_REVIEW", "BLOCKED", "FAILED"].includes(status.status)) {
          await finishGeneration(taskId, selectionEpoch, status, announce);
          return;
        }
      } catch {
        if (isCurrentSelection(taskId, selectionEpoch)) {
          setGenerateStatus("排课作业仍在后台运行，暂时无法读取最新状态...");
        }
      }
      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }
    if (isCurrentSelection(taskId, selectionEpoch) && pollEpochRef.current === pollEpoch) {
      setGenerating(false);
      setGenerationError("前端已等待30分钟，作业状态仍保存在服务端；重新选择该任务可继续恢复查询。");
      setGenerateStatus("等待超时，请稍后重新查询持久作业状态");
    }
  }

  async function loadGenerationStatus(taskId: number, selectionEpoch: number, resumePolling: boolean) {
    try {
      const status = await request.get<GenerationStatus>(`/api/allocation-tasks/${taskId}/templates/generation-status`, { suppressErrorToast: true });
      if (!isCurrentSelection(taskId, selectionEpoch)) return;
      applyGenerationStatus(taskId, selectionEpoch, status);
      if (status.status === "RUNNING" && resumePolling) {
        void pollGeneration(taskId, selectionEpoch, false);
      } else if (status.status === "SUCCESS" || status.status === "NEEDS_MANUAL_REVIEW") {
        void loadV35Templates(taskId, selectionEpoch);
      }
    } catch {
      if (isCurrentSelection(taskId, selectionEpoch)) {
        setLastGeneration(null);
        setGenerating(false);
      }
    }
  }

  async function generateSchemes() {
    if (!selectedTask) return;
    pollEpochRef.current += 1;
    const selectionEpoch = selectionEpochRef.current;
    setGenerating(true);
    setGenerationError("");
    setLastGeneration(null);
    setGenerateProgress(0);
    setGenerateStatus("正在触发 V3.5 模板排课...");
    const taskId = selectedTask.id;
    try {
      const submitted = await request.post<GenerationStatus>(`/api/allocation-tasks/${taskId}/templates/generate`, {
        importDb: true,
        truncateDb: false,
      });
      if (!isCurrentSelection(taskId, selectionEpoch)) return;
      applyGenerationStatus(taskId, selectionEpoch, submitted);
      if (["SUCCESS", "NEEDS_MANUAL_REVIEW", "BLOCKED", "FAILED"].includes(submitted.status)) {
        await finishGeneration(taskId, selectionEpoch, submitted, true);
        return;
      }
      await pollGeneration(taskId, selectionEpoch, true);
    } catch (e: any) {
      if (!isCurrentSelection(taskId, selectionEpoch)) return;
      const message = e.message || "V3.5 排课失败";
      setGenerating(false);
      setGenerationError(message);
      setGenerateStatus("排课未完成，请查看原因并修复输入后重试");
      toast.error("V3.5 排课失败: " + message);
    }
  }

  function refreshGenerationStatus() {
    if (!selectedTaskIdRef.current) return;
    pollEpochRef.current += 1;
    void loadGenerationStatus(selectedTaskIdRef.current, selectionEpochRef.current, true);
  }

  async function confirmScheme(schemeId: number) {
    try {
      await request.post(`/api/allocation-schemes/${schemeId}/confirm`);
      toast.success("方案已确认");
      if (selectedTask) selectTask(selectedTask);
    } catch { toast.error("确认失败"); }
  }

  function updateConfig(key: string, value: any) {
    setTaskForm(f => ({ ...f, generationConfig: { ...f.generationConfig, [key]: value } }));
  }

  function toggleTeachingTask(taskId: number) {
    setTaskForm(f => ({
      ...f,
      teachingTaskIds: f.teachingTaskIds.includes(taskId)
        ? f.teachingTaskIds.filter(id => id !== taskId)
        : [...f.teachingTaskIds, taskId],
    }));
  }

  function selectAllTeachingTasks(select: boolean) {
    const source = teachingTaskBatchFilter ? filteredTeachingTasks : teachingTasks;
    setTaskForm(f => ({
      ...f,
      teachingTaskIds: select
        ? [...new Set([...f.teachingTaskIds, ...source.map(t => t.id)])]
        : f.teachingTaskIds.filter(id => !source.some(t => t.id === id)),
    }));
  }

  const dayNames = ["周一","周二","周三","周四","周五","周六","周日"];

  return {
    tasks, loading, taskDialog, setTaskDialog, taskForm, setTaskForm, saving,
    selectedTask, schemes, schemesLoading, generating, generateStatus, generateProgress, generationError, lastGeneration,
    WEEKS, WEEKDAYS, PERIODS,
    detailScheme, schemeItems, schemeItemsLoading,
    teachingTasks, teachingTasksLoading,
    filteredTeachingTasks, teachingTaskBatchFilter, setTeachingTaskBatchFilter, teachingTaskBatchOptions,
    loadTasks, openTaskDialog, saveTask, deleteTask, selectTask,
    generateSchemes, refreshGenerationStatus, confirmScheme, updateConfig,
    loadSchemeItems, setDetailScheme, toggleTeachingTask, selectAllTeachingTasks,
    dayNames,
    v35Templates, v35TemplateWeeks, v35WeekTimetable, v35SelectedWeek,
    v35TemplatesLoading, loadV35Templates, loadV35WeekTimetable,
  };
}
