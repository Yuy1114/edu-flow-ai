import { useState, useEffect } from "react";
import request from "../api/request";
import { toast } from "sonner";

interface Req { id: number; reason: string; preferredTimeText: string; status: string; assignmentId: number; createdAt: string; }
interface Assignment { id: number; timeSlotId: number; courseName: string; classroomName: string; teacherName: string; classGroupName: string; weekNumber: number; dayOfWeek: number; periodIndex: number; classroomId: number; consecutiveSlots?: number; }
interface TimeSlotBrief { id: number; weekNumber: number; dayOfWeek: number; periodIndex: number; }
interface PendingMove { itemId: number; dayOfWeek: number; periodIndex: number; weekNumber: number; targetTimeSlotId?: number; }

const DAYS = ["周一","周二","周三","周四","周五","周六","周日"];

export function useAdjustment() {
  const [requests, setRequests] = useState<Req[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState("PENDING");
  const [timetableVisible, setTimetableVisible] = useState(false);
  const [currentReq, setCurrentReq] = useState<Req | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [timeSlotMap, setTimeSlotMap] = useState<Record<string, number>>({});
  const [currentWeek, setCurrentWeek] = useState(1);
  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null);
  const [savingMove, setSavingMove] = useState(false);

  useEffect(() => { void loadRequests(statusFilter); }, [statusFilter]);

  async function loadRequests(filter = statusFilter) {
    setLoading(true);
    try {
      const params = filter ? `?status=${filter}` : "";
      setRequests(await request.get(`/api/adjustment-requests${params}`));
    } finally { setLoading(false); }
  }

  async function openTimetable(row: Req) {
    const [detail, items, slots] = await Promise.all([
      request.get<Req>(`/api/adjustment-requests/${row.id}`),
      request.get<Assignment[]>("/api/course-assignments"),
      request.get<TimeSlotBrief[]>("/api/time-slots"),
    ]);
    setCurrentReq(detail);
    setAssignments(items);
    const map: Record<string, number> = {};
    slots.forEach(s => { map[`${s.weekNumber}-${s.dayOfWeek}-${s.periodIndex}`] = s.id; });
    setTimeSlotMap(map);
    const target = items.find(item => item.id === detail.assignmentId);
    if (target?.weekNumber) setCurrentWeek(target.weekNumber);
    else if (items.length > 0) { const minW = Math.min(...items.map(item => item.weekNumber)); if (minW > 0) setCurrentWeek(minW); }
    setPendingMove(null);
    setTimetableVisible(true);
  }

  async function confirmRequest(row: Req) {
    try {
      await request.post(`/api/adjustment-requests/${row.id}/confirm`, { reviewNote: "确认通过" });
      toast.success("调课已确认");
      loadRequests();
      if (timetableVisible && currentReq?.id === row.id) setTimetableVisible(false);
    } catch { toast.error("操作失败"); }
  }

  async function rejectRequest(row: Req) {
    if (!confirm("确认拒绝该调课申请？")) return;
    try {
      await request.post(`/api/adjustment-requests/${row.id}/reject`, { reviewNote: "教务拒绝" });
      toast.success("已拒绝");
      loadRequests();
      if (timetableVisible && currentReq?.id === row.id) setTimetableVisible(false);
    } catch { toast.error("操作失败"); }
  }

  const weekItems = assignments.filter(a => a.weekNumber === currentWeek);
  const allWeeks = [...new Set(assignments.map(a => a.weekNumber))].sort((a,b)=>a-b);

  function itemsAtSlot(day: number, period: number): Assignment[] {
    return weekItems
      .map(item => item.id === pendingMove?.itemId && pendingMove.targetTimeSlotId
        ? {
            ...item,
            dayOfWeek: pendingMove.dayOfWeek,
            periodIndex: pendingMove.periodIndex,
            timeSlotId: pendingMove.targetTimeSlotId,
          }
        : item)
      .filter(item => {
        const span = Math.max(1, item.consecutiveSlots || 1);
        return item.dayOfWeek === day
          && period >= item.periodIndex
          && period < item.periodIndex + span;
      });
  }

  function isAdjustTarget(item: Assignment) { return currentReq && item.id === currentReq.assignmentId; }

  function beginMove(item: Assignment) {
    if (!isAdjustTarget(item)) { toast.warning("只能移动标黄的调课片段"); return; }
    setPendingMove({ itemId: item.id, dayOfWeek: item.dayOfWeek, periodIndex: item.periodIndex, weekNumber: currentWeek });
  }

  function chooseTargetSlot(dayOfWeek: number, periodIndex: number) {
    if (!pendingMove) { toast.info("请先点击标黄的调课片段"); return; }
    const assignment = assignments.find(item => item.id === pendingMove.itemId);
    const span = Math.max(1, assignment?.consecutiveSlots || 1);
    const validStart = span === 1
      || span === 2 && [1, 3, 5, 7, 9].includes(periodIndex)
      || span === 4 && [1, 5].includes(periodIndex);
    if (!validStart || periodIndex + span - 1 > 10) {
      toast.warning(`连续${span}节课程不能从第${periodIndex}节开始`);
      return;
    }
    const missingSlot = Array.from({ length: span }, (_, offset) => periodIndex + offset)
      .some(period => !timeSlotMap[`${currentWeek}-${dayOfWeek}-${period}`]);
    if (missingSlot) { toast.warning("目标连续时间段不完整"); return; }
    const key = `${currentWeek}-${dayOfWeek}-${periodIndex}`; const tsId = timeSlotMap[key];
    if (!tsId) { toast.warning("时间段不存在"); return; }
    setPendingMove({...pendingMove, targetTimeSlotId: tsId, dayOfWeek, periodIndex, weekNumber: currentWeek });
  }

  function isPendingTarget(dayOfWeek: number, periodIndex: number) {
    const assignment = assignments.find(item => item.id === pendingMove?.itemId);
    const span = Math.max(1, assignment?.consecutiveSlots || 1);
    return Boolean(pendingMove?.targetTimeSlotId
      && pendingMove.weekNumber === currentWeek
      && pendingMove.dayOfWeek === dayOfWeek
      && periodIndex >= pendingMove.periodIndex
      && periodIndex < pendingMove.periodIndex + span);
  }

  async function saveMove() {
    if (!pendingMove?.targetTimeSlotId) return;
    setSavingMove(true);
    try {
      const orig = assignments.find(a => a.id === pendingMove.itemId);
      await request.put(`/api/course-assignments/${pendingMove.itemId}/move`, null, { params: { timeSlotId: pendingMove.targetTimeSlotId, classroomId: orig?.classroomId } });
      await request.post(`/api/adjustment-requests/${currentReq!.id}/confirm`, { reviewNote: "已通过课表位置调整" });
      toast.success("调课成功");
      setPendingMove(null);
      const [items] = await Promise.all([request.get("/api/course-assignments"), loadRequests()]);
      setAssignments(items);
    } catch {} finally { setSavingMove(false); }
  }

  return { requests, loading, statusFilter, setStatusFilter, timetableVisible, setTimetableVisible, currentReq, currentWeek, setCurrentWeek, pendingMove, setPendingMove, savingMove, weekItems, allWeeks, DAYS, itemsAtSlot, isAdjustTarget, isPendingTarget, loadRequests, openTimetable, confirmRequest, rejectRequest, beginMove, chooseTargetSlot, saveMove };
}
