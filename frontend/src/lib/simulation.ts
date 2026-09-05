export type SimulationProfile = "balanced" | "formal-mix" | "lab-heavy" | "constrained";

export interface SimulationConfig {
  seed: number;
  courses: number;
  teachers: number;
  classGroups: number;
  classrooms: number;
  profile: SimulationProfile;
}

export interface SimulationTaskPreview {
  id: string;
  course: string;
  type: "理论课" | "上机课";
  teacher: string;
  class_names: string[];
  class_group_ids: string[];
  class_count: number;
  room_type: "普通教室" | "机房";
  hours: number;
  weeks: number;
  sessions: number;
  students: number;
}

export interface CapacityIssuePreview extends SimulationTaskPreview {
  class_names: string[];
  available_capacity: number;
}

export type CapacityTier = {
  room_type: string; minimum_capacity: number; task_count: number; room_count: number;
  demand_hours: number; supply_hours: number; slack_hours: number; utilization: number | null; feasible: boolean;
};

export type ResourceCapacityPreflight = {
  kind: "necessary_nested_room_capacity";
  automatic_domain: { day_count: number; period_count: number; semester_weeks: number };
  feasible: boolean; status: "ok" | "insufficient"; tiers: CapacityTier[]; failed_tiers: CapacityTier[];
  task_without_eligible_room_count: number;
  task_without_eligible_room_preview: { source_key: string; room_type: string; student_count: number }[];
};

export interface SimulationDatasetPreview {
  simulation_id: string;
  schema_version: string;
  config: { seed: number; courses: number; teachers: number; class_groups: number; classrooms: number; profile: SimulationProfile };
  input_hash: string;
  counts: {
    teaching_tasks: number; multi_class_tasks: number; single_class_tasks: number; class_associations: number;
    teachers: number; class_groups: number; active_class_groups: number; classrooms: number;
    theory_tasks: number; lab_tasks: number; standard_rooms: number; large_rooms: number; lab_rooms: number;
    weekly_slots: number; room_week_capacity: number; lab_weekly_slots: number; lab_week_capacity: number;
    capacity_issues: number; room_seats: number; average_students: number; max_task_students: number;
    assistant_teacher_tasks: number; teacher_unavailable_tasks: number; allowed_weeks_tasks: number;
    fixed_classroom_tasks: number; candidate_classroom_tasks: number;
  };
  warning: string | null;
  resource_capacity_preflight: ResourceCapacityPreflight;
  tasks_preview: SimulationTaskPreview[];
  capacity_issues_preview: CapacityIssuePreview[];
  rooms: { name: string; type: "普通教室" | "机房"; capacity: number }[];
}

export type GridCell = { day: number; period: number; count: number; items: { course_name: string; class_names: string; classroom_name: string; student_count: number }[] };
export type TemplateGrid = { template_id: string; week_numbers: number[]; week_label: string; cells: GridCell[] };
export type TimetableView = { id: string; kind: "teacher" | "class"; name: string; fragment_count: number; template_grids: TemplateGrid[] };
export type FailureAnalysis = { reason: string; count: number; category: string; message: string; suggestions: string[]; examples: { uid: string; course: string; teacher: string; classes: string[]; student_count?: number }[] };

export type HourAuditTask = {
  uid: string; course: string; required_hours: number; pattern_hours: number;
  scheduled_hours: number; delta_hours: number; status: "exact" | "over" | "under"; placed: boolean;
};

export type HourAudit = {
  required_total_hours: number; scheduled_total_hours: number; delta_total_hours: number;
  exact_task_count: number; over_task_count: number; under_task_count: number;
  over_hours: number; under_hours: number; mismatch_count: number; tasks: HourAuditTask[];
};

export type EngineResult = {
  simulation_id: string;
  dataset: SimulationDatasetPreview;
  summary: { status: "ok" | "needs_manual_review" | "invalid"; needs_manual_review: boolean; hard_constraint_error_count: number; resource_capacity_preflight: ResourceCapacityPreflight; schedule: { completed: number; remaining: number; conflicts: Record<string, Record<string, number>>; conservation_mismatch: number; capacity_mismatch: number; unresolved_reason_counts: Record<string, number>; template_count: number; hard_conflict_count: number; hour_audit: HourAudit } };
  engine: { teaching_task_count: number; placement_task_count: number; compatibility_merge_count: number; template_count: number; unresolved_reason_counts: Record<string, number> };
  unresolved_preview: { uid: string; course: string; reason: string; student_count?: number }[];
  failure_analysis: FailureAnalysis[];
  template_grids: TemplateGrid[];
  timetable_views: TimetableView[];
  task_traces: TaskTrace[];
  artifact_files: string[];
};

export type TaskTrace = {
  source_key: string; course: string; teacher: string; classes: string[];
  pattern: { source: string; sessions_per_week: number; duration_weeks: number; consecutive_slots: number; total_hours: number; room_type: string };
  status: "scheduled" | "unresolved"; templates: string[];
  fragments: { fragment_id: string; template_id: string; week_numbers: number[]; week_label: string; day: number; period: number; room: string; duration_weeks: number; covered_hours: number }[];
  failure: { reason: string; stage?: string } | null;
};

export type BoundaryResult = { baseline_classrooms: number; rows: { classrooms: number; status: string; completed: number; remaining: number; needs_manual_review: boolean; reasons: Record<string, number> }[] };

export type TimetableEntry = {
  fragment_id: string; source_key: string; template_id: string; week_numbers: number[]; week_label: string;
  course: string; course_code: string; teacher: string; classes: string[];
  classroom: string; room_type: string; day: number; start_period: number; end_period: number;
  consecutive_slots: number; duration_weeks: number; covered_hours: number; student_count: number;
};

export type TimetableQueryResult = {
  simulation_id: string;
  filters: { templates: string[]; teachers: string[]; classes: string[]; classrooms: string[]; courses: string[] };
  query: { template_id: string | null; teacher: string | null; class_name: string | null; classroom: string | null; course: string | null };
  summary: { fragments: number; teachers: number; classes: number; classrooms: number; courses: number; occupied_segments: number; semester_occupied_segments: number };
  total: number; page: number; page_size: number; page_count: number; entries: TimetableEntry[];
};

export const INITIAL_SIMULATION_CONFIG: SimulationConfig = { seed: 20260816, courses: 1964, teachers: 541, classGroups: 362, classrooms: 320, profile: "balanced" };

export function profileLabel(profile: SimulationProfile) {
  return ({ balanced: "均衡学期", "formal-mix": "正式约束混合", "lab-heavy": "上机密集", constrained: "资源紧张" })[profile];
}

export function simulationRequest(config: SimulationConfig, simulationId?: string) {
  return { seed: config.seed, courses: config.courses, teachers: config.teachers, class_groups: config.classGroups, classrooms: config.classrooms, profile: config.profile, simulation_id: simulationId };
}
