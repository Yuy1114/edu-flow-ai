/**
 * 训练语料质检台的数据层。
 *
 * 后端把 25 万行授课记录压成约 1.7MB 的载荷：重复出现的班级、教师、教室名走
 * 下标表，周次压成 24 位掩码，(任务, 星期, 节次, 教室) 相同的落位合并成一条。
 * 这里负责把它展开成视图要用的形状。
 */

export type BoardStatus = "ok" | "missing";

/** 任务行的列序，与 Python 侧 `_build_payload` 一一对应。 */
export const T = {
  SEMESTER: 0, COURSE: 1, CODE: 2, CLASSES: 3, TEACHERS: 4, STUDENTS: 5,
  STUDENTS_OK: 6, TRAINABLE: 7, REASON: 8, RHYTHM: 9, JOINT: 10,
  SESSIONS: 11, PERIODS: 12, PEAK: 13, WEEKS: 14, TYPE: 15,
} as const;

/** 落位行的列序。 */
export const P = { TASK: 0, DAY: 1, PERIOD: 2, ROOM: 3, SPAN: 4, MASK: 5 } as const;

export type TaskRow = [
  number, number, string, number[], number[], number, number, number,
  number, string, number, number, number, number, number, string,
];
export type PlacementRow = [number, number, number, number, number, number];

export interface BoardMeta {
  semesters: string[];
  source_files: number;
  occurrence_rows: number;
  sessions: number;
  tasks: number;
  duplicates_removed: number;
  joint_ratio: number;
  class_dist: Record<string, number>;
  excluded: Record<string, number>;
  trainable: { tasks: number; sessions: number; periods: number; joint_tasks: number };
  quality: {
    teacher_name_conflict_sessions: number;
    tasks_missing_student_count: number;
    tasks_using_multiple_rooms: number;
  };
  per_semester: Record<string, { tasks: number; trainable: number; joint: number; sessions: number }>;
  evening_sessions: number;
}

export interface DatasetBoard {
  status: BoardStatus;
  dataset_dir: string;
  fingerprint: string;
  meta: BoardMeta;
  rooms: string[];
  courses: string[];
  classes: string[];
  teachers: string[];
  reasons: string[];
  tasks: TaskRow[];
  placements: PlacementRow[];
  /** status 为 missing 时才有 */
  missing?: string[];
  message?: string;
}

export interface DatasetSnapshot {
  id: number;
  fingerprint: string;
  datasetDir: string;
  sourceFiles: number;
  occurrenceRows: number;
  teachingSessions: number;
  teachingTasks: number;
  duplicatesRemoved: number;
  trainableTasks: number;
  trainableSessions: number;
  jointTasks: number;
  eveningSessions: number;
  capturedBy: string | null;
  createdAt: string;
}

export const DAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
export const MAX_WEEK = 24;

/** 位掩码里有几个周次。 */
export function weekCount(mask: number): number {
  let count = 0;
  let value = mask;
  while (value) { value &= value - 1; count += 1; }
  return count;
}

export function weeksOf(mask: number): number[] {
  const weeks: number[] = [];
  for (let week = 1; week <= MAX_WEEK; week += 1) {
    if (mask & (1 << (week - 1))) weeks.push(week);
  }
  return weeks;
}

export function hasWeek(mask: number, week: number): boolean {
  return (mask & (1 << (week - 1))) !== 0;
}

export interface BoardFilter {
  semester: number;
  trainableOnly: boolean;
}

/** 当前筛选下的任务下标。 */
export function filterTasks(board: DatasetBoard, filter: BoardFilter): number[] {
  const result: number[] = [];
  board.tasks.forEach((task, index) => {
    if (filter.semester >= 0 && task[T.SEMESTER] !== filter.semester) return;
    if (filter.trainableOnly && !task[T.TRAINABLE]) return;
    result.push(index);
  });
  return result;
}

export function filterPlacements(board: DatasetBoard, taskIds: Set<number>): PlacementRow[] {
  return board.placements.filter(row => taskIds.has(row[P.TASK]));
}

/**
 * 星期 × 节次的授课次数。按周次展开——一条落位覆盖 12 个教学周就算 12 次。
 * 续占节次不计入：起始节次记一次课，避免把连 4 节的实验课算成四节课。
 */
export function slotGrid(placements: PlacementRow[]): { grid: number[][]; max: number; total: number } {
  const grid = Array.from({ length: 12 }, () => new Array(8).fill(0));
  let total = 0;
  placements.forEach(row => {
    const times = weekCount(row[P.MASK]);
    grid[row[P.PERIOD]][row[P.DAY]] += times;
    total += times;
  });
  let max = 0;
  for (let period = 1; period <= 11; period += 1) {
    for (let day = 1; day <= 7; day += 1) max = Math.max(max, grid[period][day]);
  }
  return { grid, max, total };
}

/** 教室占用：续占节次要算进去，因为它确实占着房间。 */
export function roomGrid(placements: PlacementRow[]): { grid: number[][]; max: number } {
  const grid = Array.from({ length: 12 }, () => new Array(8).fill(0));
  placements.forEach(row => {
    const times = weekCount(row[P.MASK]);
    for (let offset = 0; offset < row[P.SPAN]; offset += 1) {
      const period = row[P.PERIOD] + offset;
      if (period <= 11) grid[period][row[P.DAY]] += times;
    }
  });
  let max = 0;
  for (let period = 1; period <= 11; period += 1) {
    for (let day = 1; day <= 7; day += 1) max = Math.max(max, grid[period][day]);
  }
  return { grid, max };
}

const HEAT_STEPS = [
  "bg-base-200",
  "bg-primary/15",
  "bg-primary/30",
  "bg-primary/50",
  "bg-primary/70",
  "bg-primary/90 text-primary-content",
];

export function heatClass(value: number, max: number): string {
  if (!value || !max) return HEAT_STEPS[0];
  const ratio = value / max;
  if (ratio <= 0.08) return HEAT_STEPS[1];
  if (ratio <= 0.25) return HEAT_STEPS[2];
  if (ratio <= 0.5) return HEAT_STEPS[3];
  if (ratio <= 0.78) return HEAT_STEPS[4];
  return HEAT_STEPS[5];
}

export const HEAT_LEGEND = HEAT_STEPS;

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}
