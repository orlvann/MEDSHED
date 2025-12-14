/**
 * TypeScript types matching the backend API contract
 */

export type Role = "admin" | "doctor" | "doctor_admin";

export type DoctorRole = "specialist" | "resident";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "Bearer";
}

export interface User {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  first_name: string | null;
  last_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Doctor {
  id: number;
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email: string | null;
  created_at: string;
  updated_at: string;
  user_is_active?: boolean | null;
  user_role?: Role | null;
}

export interface DoctorCreate {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email: string; // Required
  user_role: Role; // Required: "doctor" or "doctor_admin"
}

export interface DoctorPut {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email?: string | null;
  user_role?: Role | null;
  user_is_active?: boolean | null;
}

export interface DoctorList {
  page: number;
  size: number;
  total: number;
  items: Doctor[];
}

export interface ErrorPayload {
  detail: string;
  code: string;
  context?: Record<string, any>;
}

// Set Password types
export interface SetPasswordRequest {
  token: string;
  new_password: string;
}

export interface SetPasswordResponse {
  message: string;
}

// Admin Users types
export interface AdminUser {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  doctor_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserCreate {
  email: string;
  doctor_id?: number | null;
}

export interface AdminUserUpdate {
  email?: string | null;
  is_active?: boolean | null;
  doctor_id?: number | null;
}

export interface AdminUserList {
  page: number;
  size: number;
  total: number;
  items: AdminUser[];
}

// Preference types
export type PreferenceStatus = "missing" | "submitted";
export type DeadlineStatus = "open" | "locked";
export type PeriodStatus = "past" | "current" | "future";

// Editable preference fields (shared between PUT and Read)
export interface PreferenceEditableFields {
  // Day-level preferences (calendar days 1..31)
  unavailable_onsite_days: number[];
  unavailable_oncall_days: number[];
  preferred_onsite_days: number[];
  preferred_oncall_days: number[];

  // Monthly totals
  min_onsite_total: number | null;
  max_onsite_total: number | null;
  target_onsite_total: number | null;
  min_oncall_total: number | null;
  max_oncall_total: number | null;
  target_oncall_total: number | null;

  // Weekend refinement
  max_onsite_weekends: number | null;
  target_onsite_weekends: number | null;
  max_oncall_weekends: number | null;
  target_oncall_weekends: number | null;

  // Weekday patterns (0=Monday..6=Sunday)
  preferred_onsite_weekdays: number[];
  preferred_oncall_weekdays: number[];
  avoid_onsite_weekdays: number[];
  avoid_oncall_weekdays: number[];

  // Other preferences
  allow_weekend_consecutive_onsite_oncall: boolean;
  preferred_partners: number[];
  comments: string | null;
}

// PUT request body for autosave
export interface PreferenceWorkingPut extends PreferenceEditableFields {}

// GET response for working copy
export interface PreferenceWorkingRead extends PreferenceEditableFields {
  doctor_id: number;
  year: number;
  month: number;
  status: PreferenceStatus;
  version_id: string | null;
  submitted_at: string | null;
  submitted_by_role: string | null;
  submitted_by_user_id: number | null;
  last_admin_note: string | null;
  can_undo: boolean;
  can_redo: boolean;
  org_timezone: string;
  period_status: PeriodStatus;
}

// Response for autosave PUT
export interface PreferenceAutosaveAck {
  doctor_id: number;
  year: number;
  month: number;
  updated_at: string;
  status: PreferenceStatus;
  version_id: string | null;
  can_undo: boolean;
  can_redo: boolean;
  lock_version: number | null;
}

// Response for checkpoint POST
export interface PreferenceCheckpointCreated extends PreferenceEditableFields {
  doctor_id: number;
  year: number;
  month: number;
  status: PreferenceStatus;
  version_id: string;
  submitted_at: string;
  submitted_by_user_id: number;
  submitted_by_role: string;
  can_undo: boolean;
  can_redo: boolean;
  processed_at: string;
}

// Response for revert (undo/redo)
export interface PreferenceRevertRead extends PreferenceEditableFields {
  doctor_id: number;
  year: number;
  month: number;
  reverted_at: string;
  version_id: string;
  current_created_by_role: string;
  current_created_by_user_id: number;
  current_created_at: string;
  can_undo: boolean;
  can_redo: boolean;
}

// Summary of submissions for a period
export interface PreferencesSummaryRead {
  year: number;
  month: number;
  submitted: number[];
  missing: number[];
}

// Deadline configuration
export interface PreferencesDeadlineRead {
  year: number;
  month: number;
  deadline: string | null;
  status: DeadlineStatus;
  org_timezone: string;
}
