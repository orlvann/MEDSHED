export const RISK_ISSUE_MESSAGES: Record<string, string> = {
  // Feasibility / availability (shared with backend issues.py)
  no_onsite_candidate: "No doctor is available for onsite duty on this day.",
  no_oncall_candidate: "No doctor is available for on-call duty on this day.",
  no_specialist: "No specialist is available on this day.",
  forced_double_shift_same_day:
    "Only one doctor can cover both shifts on this day, but double shift is forbidden.",

  // Head commitment issues
  head_commitment_ignored_slot: "Head commitment targets an ignored slot.",
  head_commitment_not_allowed:
    "Head doctor is not available for the requested slot.",
  head_commitment_conflict:
    "Multiple head doctors have a commitment for the same slot.",
  head_commitment_double_shift_same_day:
    "A head doctor requests both onsite and on-call on the same day.",

  // Solver fallback
  cp_infeasible:
    "No schedule satisfies all constraints for this month.",

  // Diagnostics findings
  coverage_missing_required_slot: "Required coverage slot is missing.",
  coverage_no_specialist_day:
    "No specialist is assigned on this day (onsite specialist required).",
  hard_double_shift_same_day:
    "Doctor is assigned to both onsite and on-call on the same day.",
  coverage_ignored_day: "Day is ignored for coverage (no required slots).",
  coverage_ignored_slot: "Slot is ignored for coverage (not required).",
  rest_consecutive_violation:
    "Rest rule violation: consecutive duties without required break.",
  preference_miss: "Preferred day was not assigned.",

  // Legacy / UI-only codes (kept for backward compat)
  single_candidate_for_both_roles:
    "Only one doctor is available, roles cannot be split.",
  no_candidates_for_day: "No doctors are available for any duty on this day.",
  few_doctors_total:
    "Low availability: only a small number of doctors are available in total.",
};

export const getRiskIssueMessage = (code: string): string => {
  return RISK_ISSUE_MESSAGES[code] || `Coverage issue: ${code}`;
};
