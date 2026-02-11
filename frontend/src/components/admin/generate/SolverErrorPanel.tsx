import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../ui/button";
import { AlertTriangle, X } from "lucide-react";
import { getRiskIssueMessage } from "./riskMessages";
import type { Doctor, IgnoredSlot } from "../../../types";

// ── Helpers ──

/** Build id→"First Last" lookup from Doctor[] */
export function buildDoctorNameMap(doctors: Doctor[]): Map<number, string> {
  const map = new Map<number, string>();
  for (const d of doctors) {
    map.set(d.id, `${d.first_name} ${d.last_name}`);
  }
  return map;
}

/** Build a Link to the preferences page for a specific doctor */
function doctorLink(
  name: string,
  doctorId: number,
  year: number,
  month: number,
): ReactNode {
  return (
    <Link
      to={`/admin/preferences?year=${year}&month=${month}&doctor_id=${doctorId}`}
      className="underline hover:text-red-800 transition-colors"
      onClick={(e) => e.stopPropagation()}
    >
      {name}
    </Link>
  );
}

/** Extract (head_id=X) from backend message and replace with doctor name link */
export function enrichIssueMessage(
  raw: string,
  code: string,
  nameMap: Map<number, string>,
  year: number,
  month: number,
): ReactNode {
  const base = getRiskIssueMessage(code);

  const headIdMatch = raw.match(/\(head_id=(\d+)\)/);
  if (headIdMatch) {
    const headId = parseInt(headIdMatch[1], 10);
    const name = nameMap.get(headId);
    if (name) {
      return <>{base} ({doctorLink(name, headId, year, month)})</>;
    }
    return <>{base} (Doctor #{headId})</>;
  }

  const conflictMatch = raw.match(
    /\(.*?head_id=(\d+).*?other_head_id=(\d+)\)/,
  );
  if (conflictMatch) {
    const id1 = parseInt(conflictMatch[1], 10);
    const id2 = parseInt(conflictMatch[2], 10);
    const name1 = nameMap.get(id1);
    const name2 = nameMap.get(id2);
    const link1 = name1 ? doctorLink(name1, id1, year, month) : `Doctor #${id1}`;
    const link2 = name2 ? doctorLink(name2, id2, year, month) : `Doctor #${id2}`;
    return <>{base} ({link1} vs {link2})</>;
  }

  return base;
}

/** Format day numbers as compact ranges: [3,5,6,7,8,12] → "3, 5–8, 12" */
function formatDayRanges(days: number[]): string {
  const sorted = [...days].sort((a, b) => a - b);
  const ranges: string[] = [];
  let start = sorted[0];
  let end = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === end + 1) {
      end = sorted[i];
    } else {
      ranges.push(start === end ? `${start}` : `${start}\u2013${end}`);
      start = sorted[i];
      end = sorted[i];
    }
  }
  ranges.push(start === end ? `${start}` : `${start}\u2013${end}`);
  return ranges.join(", ");
}

interface IssueGroup {
  key: string;
  message: ReactNode;
  days: number[];
}

// ── Types for structured 409 error context ──

interface IssueSample {
  day: number;
  code: string;
  message: string;
}

interface IssueSummary {
  code: string;
  count: number;
}

interface HeadCandidate {
  doctor_id: number;
  display_name: string;
}

interface HeadConflict {
  day: number;
  shift_type: string;
  head_candidates: HeadCandidate[];
}

export interface GenerateRequiresIgnoreContext {
  year: number;
  month: number;
  issues_total: number;
  issues_truncated: boolean;
  issues_summary: IssueSummary[];
  issues_sample: IssueSample[];
  suggested_ignored_slots: IgnoredSlot[];
  suggested_ignore_reason_codes: string[];
}

export interface GenerateRequiresHeadResolutionContext {
  year: number;
  month: number;
  head_commitment_conflicts: HeadConflict[];
}

export interface HeadCommitmentResolution {
  day: number;
  shift_type: string;
  chosen_head_id: number;
}

export interface GenerateInfeasibleContext {
  year: number;
  month: number;
  solver_status: string;
  issues_total: number;
  issues_truncated: boolean;
  issues_summary: IssueSummary[];
  issues_sample: IssueSample[];
}

// ── Shared panel shell ──

function PanelShell({
  title,
  subtitle,
  onDismiss,
  children,
}: {
  title: string;
  subtitle?: string;
  onDismiss: () => void;
  children: ReactNode;
}) {
  return (
    <div className="mb-6 rounded-xl border border-red-200 bg-white overflow-hidden shadow-sm">
      {/* Red accent bar */}
      <div className="h-1 bg-red-500" />

      <div className="px-5 pt-4 pb-2 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-red-500 shrink-0" />
          <div>
            <h3 className="text-[15px] font-semibold text-gray-900 leading-tight">
              {title}
            </h3>
            {subtitle && (
              <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
            )}
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="px-5 pb-5">{children}</div>
    </div>
  );
}

// ── Panel for generate_requires_ignore ──

function buildIssueGroups(
  issues: IssueSample[],
  nameMap: Map<number, string>,
  year: number,
  month: number,
): IssueGroup[] {
  const groupMap = new Map<string, { message: ReactNode; daySet: Set<number> }>();
  for (const issue of issues) {
    const key = `${issue.code}::${issue.message}`;
    if (!groupMap.has(key)) {
      groupMap.set(key, {
        message: enrichIssueMessage(issue.message, issue.code, nameMap, year, month),
        daySet: new Set(),
      });
    }
    groupMap.get(key)!.daySet.add(issue.day);
  }
  const groups: IssueGroup[] = [];
  for (const [key, { message, daySet }] of groupMap) {
    groups.push({ key, message, days: [...daySet].sort((a, b) => a - b) });
  }
  return groups;
}

function IgnoreIssuesPanel({
  context,
  onAccept,
  onCancel,
  generating,
  doctorNameMap,
}: {
  context: GenerateRequiresIgnoreContext;
  onAccept: (ignoreSlots: IgnoredSlot[]) => void;
  onCancel: () => void;
  generating: boolean;
  doctorNameMap: Map<number, string>;
}) {
  const issueGroups = buildIssueGroups(
    context.issues_sample,
    doctorNameMap,
    context.year,
    context.month,
  );

  // Group gaps by shift type
  const gapsByType = new Map<string, Set<number>>();
  for (const slot of context.suggested_ignored_slots) {
    const label = slot.shift_type === "onsite" ? "On-site" : "On-call";
    if (!gapsByType.has(label)) gapsByType.set(label, new Set());
    gapsByType.get(label)!.add(slot.day);
  }

  const gapCount = context.suggested_ignored_slots.length;

  return (
    <PanelShell
      title="Solver found coverage issues"
      subtitle={`${context.issues_total} issue${context.issues_total !== 1 ? "s" : ""} \u00b7 ${gapCount} gap${gapCount !== 1 ? "s" : ""} will remain`}
      onDismiss={onCancel}
    >
      {/* Issues grouped by type */}
      <div className="mt-3 space-y-px rounded-lg border border-gray-200 overflow-hidden max-h-[280px] overflow-y-auto">
        {issueGroups.map((group) => (
          <div
            key={group.key}
            className="px-3.5 py-2.5 bg-gray-50/70 border-b border-gray-100 last:border-b-0"
          >
            <p className="text-[13px] text-gray-700 leading-snug">{group.message}</p>
            <span className="text-xs text-gray-400 mt-0.5 block tabular-nums">
              Day{group.days.length > 1 ? "s" : ""} {formatDayRanges(group.days)}
            </span>
          </div>
        ))}
        {[...gapsByType].map(([type, daySet]) => (
          <div
            key={type}
            className="px-3.5 py-2.5 bg-red-50/50 border-b border-gray-100 last:border-b-0"
          >
            <span className="text-[13px] text-red-600 font-medium">
              Gap: {type}
            </span>
            <span className="text-xs text-gray-400 mt-0.5 block tabular-nums">
              Day{daySet.size > 1 ? "s" : ""} {formatDayRanges([...daySet])}
            </span>
          </div>
        ))}
      </div>

      {context.issues_truncated && (
        <p className="text-xs text-gray-400 mt-2">
          Showing a sample of {context.issues_total} total issues.
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-3 mt-4">
        <Button
          variant="outline"
          className="flex-1"
          onClick={onCancel}
          disabled={generating}
        >
          Cancel
        </Button>
        <Button
          className="flex-1 bg-red-600 hover:bg-red-700 text-white"
          onClick={() => onAccept(context.suggested_ignored_slots)}
          disabled={generating}
        >
          {generating ? "Generating\u2026" : "Accept gaps & generate"}
        </Button>
      </div>
    </PanelShell>
  );
}

// ── Panel for generate_requires_head_resolution ──

function HeadConflictPanel({
  context,
  onAccept,
  onCancel,
  generating,
}: {
  context: GenerateRequiresHeadResolutionContext;
  onAccept: (resolutions: HeadCommitmentResolution[]) => void;
  onCancel: () => void;
  generating: boolean;
}) {
  const [resolutions, setResolutions] = useState<
    Record<string, number | null>
  >({});

  const conflicts = context.head_commitment_conflicts;

  const setResolution = (day: number, shiftType: string, headId: number) => {
    setResolutions((prev) => ({ ...prev, [`${day}-${shiftType}`]: headId }));
  };

  const allResolved = conflicts.every(
    (c) => resolutions[`${c.day}-${c.shift_type}`] != null
  );

  const handleAccept = () => {
    const resolved: HeadCommitmentResolution[] = conflicts
      .filter((c) => resolutions[`${c.day}-${c.shift_type}`] != null)
      .map((c) => ({
        day: c.day,
        shift_type: c.shift_type,
        chosen_head_id: resolutions[`${c.day}-${c.shift_type}`]!,
      }));
    onAccept(resolved);
  };

  return (
    <PanelShell
      title="Head doctor conflicts"
      subtitle="Choose who gets each contested slot."
      onDismiss={onCancel}
    >
      <div className="mt-3 space-y-3">
        {conflicts.map((conflict) => {
          const key = `${conflict.day}-${conflict.shift_type}`;
          const selectedId = resolutions[key] ?? null;

          return (
            <div
              key={key}
              className="rounded-lg border border-gray-200 overflow-hidden"
            >
              <div className="px-3.5 py-2 bg-gray-50 border-b border-gray-100 text-sm font-semibold text-gray-900">
                Day {conflict.day} &mdash;{" "}
                {conflict.shift_type === "onsite" ? "On-site" : "On-call"}
              </div>
              <div className="p-1.5 space-y-1">
                {conflict.head_candidates.map((candidate) => (
                  <label
                    key={candidate.doctor_id}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-md cursor-pointer transition-colors text-sm ${
                      selectedId === candidate.doctor_id
                        ? "bg-blue-50 text-blue-900"
                        : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    <input
                      type="radio"
                      name={key}
                      checked={selectedId === candidate.doctor_id}
                      onChange={() =>
                        setResolution(
                          conflict.day,
                          conflict.shift_type,
                          candidate.doctor_id
                        )
                      }
                      className="accent-blue-600"
                    />
                    {candidate.display_name}
                  </label>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div className="flex gap-3 mt-4">
        <Button
          variant="outline"
          className="flex-1"
          onClick={onCancel}
          disabled={generating}
        >
          Cancel
        </Button>
        <Button
          className="flex-1"
          onClick={handleAccept}
          disabled={!allResolved || generating}
        >
          {generating ? "Generating\u2026" : "Resolve & generate"}
        </Button>
      </div>
    </PanelShell>
  );
}

// ── Panel for generate_infeasible ──

function InfeasiblePanel({
  context,
  onDismiss,
  doctorNameMap,
}: {
  context: GenerateInfeasibleContext;
  onDismiss: () => void;
  doctorNameMap: Map<number, string>;
}) {
  const issueGroups = buildIssueGroups(
    context.issues_sample,
    doctorNameMap,
    context.year,
    context.month,
  );

  return (
    <PanelShell
      title="Solver could not find a solution"
      subtitle="Change inputs (availability, limits, preferences) and try again."
      onDismiss={onDismiss}
    >
      {issueGroups.length > 0 && (
        <div className="mt-3 space-y-px rounded-lg border border-gray-200 overflow-hidden max-h-[240px] overflow-y-auto">
          {issueGroups.map((group) => (
            <div
              key={group.key}
              className="px-3.5 py-2.5 bg-gray-50/70 border-b border-gray-100 last:border-b-0"
            >
              <p className="text-[13px] text-gray-700 leading-snug">{group.message}</p>
              <span className="text-xs text-gray-400 mt-0.5 block tabular-nums">
                Day{group.days.length > 1 ? "s" : ""} {formatDayRanges(group.days)}
              </span>
            </div>
          ))}
        </div>
      )}

      {context.issues_truncated && (
        <p className="text-xs text-gray-400 mt-2">
          Showing a sample of {context.issues_total} total issues.
        </p>
      )}
    </PanelShell>
  );
}

// ── Main export: renders the right panel based on error code ──

export interface SolverErrorData {
  code: string;
  detail: string;
  context: any;
}

interface SolverErrorPanelProps {
  error: SolverErrorData;
  onRetryWithIgnore: (ignoreSlots: IgnoredSlot[]) => void;
  onRetryWithHeadResolution: (
    resolutions: HeadCommitmentResolution[],
    ignoreSlots: IgnoredSlot[]
  ) => void;
  onDismiss: () => void;
  generating: boolean;
  doctors: Doctor[];
}

export const SolverErrorPanel = ({
  error,
  onRetryWithIgnore,
  onRetryWithHeadResolution,
  onDismiss,
  generating,
  doctors,
}: SolverErrorPanelProps) => {
  const doctorNameMap = buildDoctorNameMap(doctors);
  switch (error.code) {
    case "generate_requires_ignore":
      return (
        <IgnoreIssuesPanel
          context={error.context as GenerateRequiresIgnoreContext}
          onAccept={onRetryWithIgnore}
          onCancel={onDismiss}
          generating={generating}
          doctorNameMap={doctorNameMap}
        />
      );

    case "generate_requires_head_resolution":
      return (
        <HeadConflictPanel
          context={error.context as GenerateRequiresHeadResolutionContext}
          onAccept={(resolutions) =>
            onRetryWithHeadResolution(resolutions, [])
          }
          onCancel={onDismiss}
          generating={generating}
        />
      );

    case "generate_infeasible":
      return (
        <InfeasiblePanel
          context={error.context as GenerateInfeasibleContext}
          onDismiss={onDismiss}
          doctorNameMap={doctorNameMap}
        />
      );

    default:
      return (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error.detail}
        </div>
      );
  }
};
