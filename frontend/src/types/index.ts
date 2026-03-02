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
  phone_number: string | null;
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
  phone_number: string | null;
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
  phone_number?: string;
  user_role: Role; // Required: "doctor" or "doctor_admin"
}

export interface DoctorPut {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email?: string | null;
  phone_number?: string | null;
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

// Schedule types
export type ShiftType = "onsite" | "oncall";
export type ScheduleStatus = "draft" | "published";

export interface Assignment {
  day: number;
  shift_type: ShiftType;
  doctor_id: number;
}

// Inputs snapshot (frozen doctor data at generation time)
export interface DoctorSnapshotRead {
  role: DoctorRole;
  is_head: boolean;
  display_name: string;
  is_active_at_snapshot: boolean;
}

export interface InputsSnapshotRead {
  doctors: Record<number, DoctorSnapshotRead>;
  preference_version_id_by_doctor: Record<number, number | null>;
}

export interface SchedulePayload {
  participant_doctor_ids: number[];
  assignments: Assignment[];
  inputs_snapshot: InputsSnapshotRead | null;
  meta: Record<string, any>;
}

// Working buffer
export interface ScheduleWorkingRead {
  year: number;
  month: number;
  exists: boolean;
  participant_doctor_ids: number[];
  assignments: Assignment[];
  meta: Record<string, any>;
  updated_at: string | null;
  lock_version: number | null;
  inputs_snapshot: InputsSnapshotRead | null;
}

export interface ScheduleWorkingPut {
  assignments: Assignment[];
  meta?: Record<string, any> | null;
  if_match_lock_version?: number | null;
}

export interface ScheduleWorkingAck {
  year: number;
  month: number;
  updated_at: string;
  lock_version: number | null;
}

// Draft view
export interface ScheduleDraftView {
  version_id: number | null;
  checkpoints_count: number;
  can_undo: boolean;
  can_redo: boolean;
  payload: SchedulePayload | null;
}

// Published view
export interface SchedulePublishedView {
  version_id: number | null;
  publications_count: number;
  can_undo: boolean;
  can_redo: boolean;
  audit: Record<string, unknown> | null;
  payload: SchedulePayload | null;
}

// Period view (main admin endpoint)
export interface ViewHint {
  default_mode: "draft" | "published";
  toggle_available: boolean;
}

export interface SchedulesPeriodViewRead {
  year: number;
  month: number;
  org_timezone: string;
  period_status: PeriodStatus;
  view: ViewHint;
  working: ScheduleWorkingRead;
  draft: ScheduleDraftView;
  published: SchedulePublishedView;
  diagnostics: DiagnosticsRead | null;
}

// Published-only read (doctor path)
export interface SchedulePublishedRead {
  year: number;
  month: number;
  org_timezone: string;
  period_status: PeriodStatus;
  published: SchedulePublishedView;
}

// Diagnostics
export interface DiagnosticsSummaryRead {
  coverage_missing_required_slots: number;
  hard_issues_count: number;
  rest_violations: number;
  fairness_index: number;
  preference_fulfillment_pct: number;
}

export interface DiagnosticsFindingRead {
  code: string;
  severity: "critical" | "warning" | "info";
  context: Record<string, any>;
}

export interface CategoryBaseRead {
  applicable: boolean;
  badness: number;
  stars: number | null;
}

export interface DoctorCategoriesRead {
  rest: CategoryBaseRead;
  preferred_days: CategoryBaseRead;
  fairness: CategoryBaseRead;
  totals: CategoryBaseRead;
  weekday_patterns: CategoryBaseRead;
  friday_free_weekend: CategoryBaseRead;
  preferred_partners: CategoryBaseRead;
}

export interface SolverComponentsByDocRead {
  [key: string]: any;
}

export interface DoctorDiagnosticsRead {
  doctor_id: number;
  display_name: string;
  assigned_onsite_total: number;
  assigned_oncall_total: number;
  rest_violations: number;
  preferred_days_requested: number;
  preferred_days_missed: number;
  preference_fulfillment_pct: number;
  ui_stars: number | null;
  ui_reasons_codes: string[];
  categories: DoctorCategoriesRead;
  solver_components_by_doc: SolverComponentsByDocRead;
}

export interface DoctorRankingItemRead {
  doctor_id: number;
  score: number;
  reasons_codes: string[];
}

export interface RankingsRead {
  unhappy: DoctorRankingItemRead[];
  happy: DoctorRankingItemRead[];
}

export interface DiagnosticsAuditItemRead {
  kind: "generation_ignore" | "publish_acceptance" | "head_commitment_resolution" | null;
  code: string;
  day: number | null;
  shift_type: string | null;
  justification: string | null;
  accepted_by_user_id: number | null;
  accepted_at: string | null;
}

export interface DiagnosticsDetailsRead {
  findings: DiagnosticsFindingRead[];
  per_doctor: DoctorDiagnosticsRead[];
  rankings: RankingsRead;
  audit: DiagnosticsAuditItemRead[];
  solver_components_total: Record<string, any>;
  working_lock_version: number | null;
}

export interface DiagnosticsRead {
  version_id: number | null;
  computed_at: string;
  summary: DiagnosticsSummaryRead;
  details: DiagnosticsDetailsRead | null;
}

// Doctor-facing diagnostics (privacy-safe, single doctor only)
export interface MyDoctorDiagnosticsRead {
  version_id: number;
  computed_at: string;
  doctor: DoctorDiagnosticsRead;
}

// Checkpoint/Revert/Publish
export interface ScheduleCheckpointRequest {
  note?: string | null;
}

export interface ScheduleCheckpointCreated {
  year: number;
  month: number;
  draft: ScheduleDraftView;
  diagnostics: DiagnosticsRead;
}

export interface ScheduleRevertRead {
  year: number;
  month: number;
  draft: ScheduleDraftView;
  working: ScheduleWorkingRead;
  diagnostics: DiagnosticsRead;
}

export interface AcceptedException {
  code: string;
  justification?: string | null;
}

export interface SchedulePublishRequest {
  force?: boolean;
  note?: string | null;
  accepted_exceptions?: AcceptedException[];
}

export interface SchedulePublishCreated {
  year: number;
  month: number;
  published: SchedulePublishedView;
}

export interface SchedulePublishedRevertRead {
  year: number;
  month: number;
  published: SchedulePublishedView;
}

export interface MyAssignment {
  day: number;
  shift_type: ShiftType;
}

export interface MyAssignmentsRead {
  doctor_id: number;
  year: number;
  month: number;
  assignments: MyAssignment[];
}

// Availability types
export type RiskLevel = "ok" | "alert" | "critical";

export interface DoctorMini {
  id: number;
  first_name: string;
  last_name: string;
}

export interface IgnoredSlot {
  day: number;
  shift_type: ShiftType;
}

export interface AvailabilityDayOverview {
  day: number;
  available_specialists_onsite: number;
  available_residents_onsite: number;
  available_specialists_oncall: number;
  available_residents_oncall: number;
  risk: RiskLevel;
  risk_issues: string[];
  suggested_ignored_slots: IgnoredSlot[];
  suggested_ignore_reason_codes: string[];
}

export interface AvailabilityOverviewRead {
  year: number;
  month: number;
  days: AvailabilityDayOverview[];
}

export interface AvailabilityDayRead {
  year: number;
  month: number;
  day: number;
  specialists_onsite: DoctorMini[];
  residents_onsite: DoctorMini[];
  specialists_oncall: DoctorMini[];
  residents_oncall: DoctorMini[];
  risk: RiskLevel;
  risk_issues: string[];
  suggested_ignored_slots: IgnoredSlot[];
  suggested_ignore_reason_codes: string[];
}

// Schedule generation types
export interface HeadCommitmentResolution {
  day: number;
  shift_type: string;
  chosen_head_id: number;
}

export interface ScheduleGenerateRequest {
  year: number;
  month: number;
  participant_doctor_ids: number[];
  ignore_slots: IgnoredSlot[];
  justification?: string;
  head_commitment_resolutions?: HeadCommitmentResolution[];
}

export interface ScheduleGenerateCreated {
  year: number;
  month: number;
  status: ScheduleStatus;
  working: ScheduleWorkingRead;
  draft: ScheduleDraftView;
  diagnostics: DiagnosticsRead;
}
