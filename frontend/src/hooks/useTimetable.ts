import { useState, useEffect, useMemo } from "react";
import request from "../api/request";

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
  weekNumber: "", dayOfWeek: "", status: "ACTIVE",
};

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
  const [hourAudit, setHourAudit] = useState<AssignmentHourAudit | null>(null);

  useEffect(() => {
    void loadAssignments();
    void loadReferenceData();
  }, []);

  async function loadReferenceData() {
    const unwrap = (value: any) => Array.isArray(value) ? value : value?.content ?? [];
    try {
      const [teacherRows, classRows, courseRows, roomRows] = await Promise.all([
        request.get("/api/teachers"),
        request.get("/api/class-groups"),
        request.get("/api/courses"),
        request.get("/api/classrooms"),
      ]);
      setTeachers(unwrap(teacherRows));
      setClassGroups(unwrap(classRows));
      setCourses(unwrap(courseRows));
      setClassrooms(unwrap(roomRows));
    } catch {
      setTeachers([]); setClassGroups([]); setCourses([]); setClassrooms([]);
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

  function resetFilters() {
    setFilters(DEFAULT_FILTERS);
    void loadAssignments(DEFAULT_FILTERS);
  }

  return {
    assignments, hourAudit, loading, viewMode, setViewMode,
    currentWeek, setCurrentWeek,
    filters, setFilters,
    teachers, classGroups, courses, classrooms,
    weekItems, allWeeks, dayNames,
    itemsAtSlot,
    loadAssignments,
    resetFilters,
  };
}
