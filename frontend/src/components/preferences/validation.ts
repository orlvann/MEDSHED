import type { PreferenceWorkingPut } from "../../types";
import { getMonthDayCounts } from "./types";

export interface ValidationError {
  field: string;
  message: string;
}

export interface ValidationResult {
  isValid: boolean;
  errors: ValidationError[];
}

/**
 * Validates preference form data.
 *
 * Rules:
 * - No negative numbers
 * - Preferred days count must not exceed max limits
 *
 * Note: Target values are auto-clamped to max in ShiftCountsGrid,
 * so we don't need to validate target <= max here.
 */
export function validatePreferences(
  data: PreferenceWorkingPut,
  year: number,
  month: number
): ValidationResult {
  const errors: ValidationError[] = [];

  // Rule: No negative numbers for all numeric fields
  const numericFields = [
    { field: "max_onsite_total", label: "I can (on-site total)" },
    { field: "target_onsite_total", label: "I want (on-site total)" },
    { field: "max_oncall_total", label: "I can (on-call total)" },
    { field: "target_oncall_total", label: "I want (on-call total)" },
    { field: "max_onsite_weekends", label: "I can (on-site weekends)" },
    { field: "target_onsite_weekends", label: "I want (on-site weekends)" },
    { field: "max_oncall_weekends", label: "I can (on-call weekends)" },
    { field: "target_oncall_weekends", label: "I want (on-call weekends)" },
  ] as const;

  for (const { field, label } of numericFields) {
    const value = data[field as keyof PreferenceWorkingPut] as number | null;
    if (value !== null && value < 0) {
      errors.push({
        field,
        message: `${label} cannot be negative`,
      });
    }
  }

  // Rule: Target (I want) cannot exceed max (I can)
  const targetMaxPairs = [
    {
      target: "target_onsite_total",
      max: "max_onsite_total",
      label: "on-site weekdays",
    },
    {
      target: "target_onsite_weekends",
      max: "max_onsite_weekends",
      label: "on-site weekends",
    },
    {
      target: "target_oncall_total",
      max: "max_oncall_total",
      label: "on-call weekdays",
    },
    {
      target: "target_oncall_weekends",
      max: "max_oncall_weekends",
      label: "on-call weekends",
    },
  ] as const;

  for (const { target, max, label } of targetMaxPairs) {
    const targetValue = data[target] as number | null;
    const maxValue = data[max] as number | null;
    if (targetValue !== null && maxValue !== null && targetValue > maxValue) {
      errors.push({
        field: target,
        message: `"I want" (${targetValue}) cannot exceed "I can" (${maxValue}) for ${label}`,
      });
    }
  }

  // Rule: Values cannot exceed available days in month
  const monthCounts = getMonthDayCounts(year, month);

  const dayLimitFields = [
    {
      field: "max_onsite_total",
      limit: monthCounts.weekdays,
      label: "on-site weekdays",
      type: "weekdays",
    },
    {
      field: "target_onsite_total",
      limit: monthCounts.weekdays,
      label: "on-site weekdays",
      type: "weekdays",
    },
    {
      field: "max_oncall_total",
      limit: monthCounts.weekdays,
      label: "on-call weekdays",
      type: "weekdays",
    },
    {
      field: "target_oncall_total",
      limit: monthCounts.weekdays,
      label: "on-call weekdays",
      type: "weekdays",
    },
    {
      field: "max_onsite_weekends",
      limit: monthCounts.weekends,
      label: "on-site weekends",
      type: "weekends",
    },
    {
      field: "target_onsite_weekends",
      limit: monthCounts.weekends,
      label: "on-site weekends",
      type: "weekends",
    },
    {
      field: "max_oncall_weekends",
      limit: monthCounts.weekends,
      label: "on-call weekends",
      type: "weekends",
    },
    {
      field: "target_oncall_weekends",
      limit: monthCounts.weekends,
      label: "on-call weekends",
      type: "weekends",
    },
  ] as const;

  for (const { field, limit, type } of dayLimitFields) {
    const value = data[field as keyof PreferenceWorkingPut] as number | null;
    if (value !== null && value > limit) {
      errors.push({
        field,
        message: `Cannot exceed ${limit} ${type} in this month`,
      });
    }
  }

  // Note: Calendar preferred days are not validated against max limits.
  // Users can freely set calendar preferences and shift counts independently.

  return {
    isValid: errors.length === 0,
    errors,
  };
}

/**
 * Get error message for a specific field.
 */
export function getFieldError(
  errors: ValidationError[],
  field: string
): string | null {
  const error = errors.find((e) => e.field === field);
  return error?.message ?? null;
}

/**
 * Check if a specific field has an error.
 */
export function hasFieldError(
  errors: ValidationError[],
  field: string
): boolean {
  return errors.some((e) => e.field === field);
}
