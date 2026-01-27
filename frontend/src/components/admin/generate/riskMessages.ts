export const RISK_ISSUE_MESSAGES: Record<string, string> = {
  no_onsite_candidate: "No doctor is available for onsite duty on this day.",
  no_oncall_candidate: "No doctor is available for on-call duty on this day.",
  no_specialist: "No specialist is available on this day.",
  single_candidate_for_both_roles:
    "Only one doctor is available, roles cannot be split.",
  no_candidates_for_day: "No doctors are available for any duty on this day.",
  few_doctors_total:
    "Low availability: only a small number of doctors are available in total.",
};

export const getRiskIssueMessage = (code: string): string => {
  return RISK_ISSUE_MESSAGES[code] || `Coverage issue: ${code}`;
};
