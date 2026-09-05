export const PERIOD_MINUTES = 45;

export const ALL_PERIODS = Object.freeze(Array.from({ length: 10 }, (_, index) => index + 1));
export const AUTO_SCHEDULING_PERIODS = Object.freeze(ALL_PERIODS.slice(0, 8));
export const EVENING_PERIODS = Object.freeze(ALL_PERIODS.slice(8));

export const DEFAULT_ALLOWED_PERIODS = AUTO_SCHEDULING_PERIODS.join(",");

export function periodSegment(period: number): "上午" | "下午" | "晚上" {
  if (period <= 4) return "上午";
  if (period <= 8) return "下午";
  return "晚上";
}

export function periodLabel(period: number): string {
  return `第${period}节`;
}

export function periodDetailLabel(period: number): string {
  return `${periodLabel(period)} · ${periodSegment(period)}`;
}

export function parsePeriodSelection(value: unknown): number[] {
  if (Array.isArray(value)) {
    return value.map(Number).filter(period => Number.isInteger(period) && period >= 1 && period <= 10);
  }
  if (typeof value === "string") {
    return value.split(",").map(Number).filter(period => Number.isInteger(period) && period >= 1 && period <= 10);
  }
  return [...AUTO_SCHEDULING_PERIODS];
}
