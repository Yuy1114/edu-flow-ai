import { useState, useEffect, useMemo } from "react";
import { toast } from "sonner";
import request from "../api/request";
import { saveBlob } from "../lib/download";

export interface Assignment {
  id: number;
  teacherId?: number;
  classGroupId?: number;
  courseId?: number;
  classroomId?: number;
  courseName: string;
  classGroupName: string;
  teacherName: string;
  classroomName: string;
  timeSlotLabel: string;
  weekNumber: number;
  dayOfWeek: number;
  periodIndex: number;
  consecutiveSlots?: number;
  status: string;
}

interface ReferenceOption { id: number; name: string; code?: string; }

export interface AssignmentHourAudit {
  requiredTotalHours: number;
  scheduledTotalHours: number;
  deltaTotalHours: number;
  mismatchTaskCount: number;
  tasks: Array<{
    teachingTaskId: number;
    courseName: string;
    requiredHours: number;
    scheduledHours: number;
    deltaHours: number;
    status: "OK" | "UNDER" | "OVER";
  }>;
}

const DEFAULT_FILTERS = {
  teacherId: "", classGroupId: "", courseId: "", classroomId: "",
  allocationTaskId: "", weekNumber: "", dayOfWeek: "", status: "ACTIVE",
};

export const EXPORT_ROLES = [
  { value: "TEACHER", label: "教师课表" },
  { value: "CLASS", label: "班级课表" },
  { value: "CLASSROOM", label: "教室占用表" },
  { value: "REGISTRAR", label: "教务总表" },
] as const;

export type ExportRole = (typeof EXPORT_ROLES)[number]["value"];

const dayNames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function useTimetable() {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");
  const [currentWeek, setCurrentWeek] = useState(1);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [teachers, setTeachers] = useState<ReferenceOption[]>([]);
  const [classGroups, setClassGroups] = useState<ReferenceOption[]>([]);
  const [courses, setCourses] = useState<ReferenceOption[]>([]);
  const [classrooms, setClassrooms] = useState<ReferenceOption[]>([]);
  const [allocationTasks, setAllocationTasks] = useState<ReferenceOption[]>([]);
  const [hourAudit, setHourAudit] = useState<AssignmentHourAudit | null>(null);
  const [exporting, setExporting] = useState<ExportRole | null>(null);

  useEffect(() => {
    void loadAssignments();
    void loadReferenceData();
  }, []);

  async function loadReferenceData() {
    const unwrap = (value: any) => Array.isArray(value) ? value : value?.content ?? [];
    try {
      const [teacherRows, classRows, courseRows, roomRows, taskRows] = await Promise.all([
        request.get("/api/teachers"),
        request.get("/api/class-groups"),
        request.get("/api/courses"),
        request.get("/api/classrooms"),
        request.get("/api/allocation-tasks"),
      ]);
      setTeachers(unwrap(teacherRows));
      setClassGroups(unwrap(classRows));
      setCourses(unwrap(courseRows));
      setClassrooms(unwrap(roomRows));
      setAllocationTasks(unwrap(taskRows));
    } catch {
      setTeachers([]); setClassGroups([]); setCourses([]); setClassrooms([]); setAllocationTasks([]);
    }
  }

  async function loadAssignments(activeFilters = filters) {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(activeFilters).forEach(([k, v]) => { if (v) params.append(k, v); });
      const qs = params.toString();
      const [data, audit] = await Promise.all([
        request.get<Assignment[]>(`/api/course-assignments${qs ? "?" + qs : ""}`),
        request.get<AssignmentHourAudit>("/api/course-assignments/hour-audit"),
      ]);
      setAssignments(data);
      setHourAudit(audit);
      if (data.length > 0) {
        const minWeek = Math.min(...data.map(a => a.weekNumber));
        if (minWeek > 0) setCurrentWeek(minWeek);
      }
    } finally { setLoading(false); }
  }

  const weekItems = useMemo(() =>
    assignments.filter(a => a.weekNumber === currentWeek),
    [assignments, currentWeek]
  );

  const allWeeks = useMemo(() =>
    [...new Set(assignments.map(a => a.weekNumber))].sort((a, b) => a - b),
    [assignments]
  );

  function itemsAtSlot(dayOfWeek: number, periodIndex: number) {
    return weekItems.filter(a => {
      const span = Math.max(1, a.consecutiveSlots || 1);
      return a.dayOfWeek === dayOfWeek
        && periodIndex >= a.periodIndex
        && periodIndex < a.periodIndex + span;
    });
  }

  /** 导出当前筛选条件下的课表；条件与页面查询完全一致，导出的就是屏幕上这份。 */
  async function exportTimetable(role: ExportRole, activeFilters = filters) {
    setExporting(role);
    try {
      const params = new URLSearchParams({ role });
      Object.entries(activeFilters).forEach(([k, v]) => { if (v) params.append(k, v); });
      const { blob, fileName } = await request.download(`/api/exports/timetable?${params.toString()}`);
      saveBlob(blob, fileName || `${role}.xlsx`);
      toast.success(`已导出 ${fileName || role}`);
    } catch {
      // 失败原因由响应拦截器统一提示（例如筛选过宽导致分表过多）
    } finally {
      setExporting(null);
    }
  }

  function resetFilters() {
    setFilters(DEFAULT_FILTERS);
    void loadAssignments(DEFAULT_FILTERS);
  }

  return {
    assignments, hourAudit, loading, viewMode, setViewMode,
    currentWeek, setCurrentWeek,
    filters, setFilters,
    teachers, classGroups, courses, classrooms, allocationTasks,
    weekItems, allWeeks, dayNames,
    itemsAtSlot,
    loadAssignments,
    resetFilters,
    exportTimetable, exporting,
  };
}
