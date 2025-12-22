import type { PreferenceWorkingPut } from "../../types";

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
 *
 * Note: Target values are auto-clamped to max in ShiftCountsGrid,
 * so we don't need to validate target <= max here.
 */
export function validatePreferences(
  data: PreferenceWorkingPut
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
export function hasFieldError(errors: ValidationError[], field: string): boolean {
  return errors.some((e) => e.field === field);
}
