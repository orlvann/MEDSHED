import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../ui/card";
import {
  AlertTriangle,
  CheckCircle,
  Info,
  ChevronDown,
  ChevronRight,
  Star,
  ShieldAlert,
  AlertOctagon,
  Clock,
  Scale,
  Heart,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import type {
  DiagnosticsRead,
  DiagnosticsFindingRead,
  DoctorDiagnosticsRead,
} from "../../../types";

interface DiagnosticsPanelProps {
  diagnostics: DiagnosticsRead | null;
}

// ---------- Finding descriptions & context rendering ----------

interface FindingInfo {
  title: string;
  description: string;
  tip?: string;
}

/** Build a doctor name lookup from per_doctor diagnostics. */
function buildDoctorNameMap(perDoctor: DoctorDiagnosticsRead[]): Map<number, string> {
  const map = new Map<number, string>();
  for (const d of perDoctor) {
    map.set(d.doctor_id, d.display_name);
  }
  return map;
}

function doctorLabel(id: number, nameMap: Map<number, string>): string {
  return nameMap.get(id) ?? `Doctor #${id}`;
}

const REST_KIND_LABELS: Record<string, string> = {
  onsite_onsite: "Onsite → Onsite on consecutive days",
  oncall_oncall: "Oncall → Oncall on consecutive days",
  cross: "Onsite/Oncall mix on consecutive days",
};

/**
 * Build a structured description for each finding code using its context.
 * Returns a title (short label), description (human sentence), and optional tip.
 */
function describeFinding(
  code: string,
  ctx: Record<string, any>,
  nameMap: Map<number, string>,
): FindingInfo {
  switch (code) {
    case "coverage_missing_required_slot": {
      const shift = ctx.shift_type === "onsite" ? "Onsite" : "Oncall";
      const ignored = ctx.was_ignored
        ? " (this slot was previously accepted as ignored)"
        : "";
      return {
        title: "Coverage gap",
        description: `Day ${ctx.day} — no doctor assigned to the ${shift} shift${ignored}.`,
        tip: "Every day must have a doctor assigned to both Onsite and Oncall shifts.",
      };
    }

    case "coverage_no_specialist_day": {
      const ignored =
        ctx.was_ignored_day || ctx.was_ignored_onsite || ctx.was_ignored_oncall;
      const suffix = ignored ? " (partially ignored during generation)" : "";
      return {
        title: "No specialist on duty",
        description: ctx.day_empty
          ? `Day ${ctx.day} — no doctors assigned at all${suffix}.`
          : `Day ${ctx.day} — assigned doctors are all residents, no specialist covers either shift${suffix}.`,
        tip: "At least one specialist must be assigned on every day (on any shift).",
      };
    }

    case "hard_double_shift_same_day": {
      const name = doctorLabel(ctx.doctor_id, nameMap);
      return {
        title: "Double shift on same day",
        description: `${name} is assigned to both Onsite and Oncall on Day ${ctx.day}.`,
        tip: "A doctor cannot work two shifts on the same day. Reassign one of the shifts.",
      };
    }

    case "rest_consecutive_violation": {
      const name = doctorLabel(ctx.doctor_id, nameMap);
      const kindLabel = REST_KIND_LABELS[ctx.kind] ?? ctx.kind;
      const crossInfo = ctx.cross_month
        ? ` (spanning from previous month — Day ${ctx.prev_day}/${ctx.prev_month})`
        : "";
      return {
        title: "Rest violation",
        description: `${name} — ${kindLabel} at Day ${ctx.day}${crossInfo}.`,
        tip: "Doctors need at least one rest day between consecutive shift assignments.",
      };
    }

    case "preference_miss": {
      const name = doctorLabel(ctx.doctor_id, nameMap);
      const shift = ctx.shift_type === "onsite" ? "Onsite" : "Oncall";
      return {
        title: "Preference not fulfilled",
        description: `${name} requested ${shift} on Day ${ctx.day} but was not assigned.`,
      };
    }

    default:
      return {
        title: code.replace(/_/g, " "),
        description: Object.entries(ctx)
          .map(([k, v]) => `${k}: ${v}`)
          .join(", "),
      };
  }
}

const SEVERITY_CONFIG = {
  critical: {
    icon: AlertTriangle,
    bg: "bg-red-50",
    border: "border-red-200",
    text: "text-red-800",
    badge: "bg-red-100 text-red-700",
    headerBg: "bg-red-100/60",
    headerText: "text-red-900",
    countBadge: "bg-red-200 text-red-800",
    label: "Critical",
  },
  warning: {
    icon: AlertTriangle,
    bg: "bg-yellow-50",
    border: "border-yellow-200",
    text: "text-yellow-800",
    badge: "bg-yellow-100 text-yellow-700",
    headerBg: "bg-yellow-100/60",
    headerText: "text-yellow-900",
    countBadge: "bg-yellow-200 text-yellow-800",
    label: "Warning",
  },
  info: {
    icon: Info,
    bg: "bg-blue-50",
    border: "border-blue-200",
    text: "text-blue-800",
    badge: "bg-blue-100 text-blue-700",
    headerBg: "bg-blue-100/60",
    headerText: "text-blue-900",
    countBadge: "bg-blue-200 text-blue-800",
    label: "Info",
  },
};

function ProgressBar({
  value,
  max = 100,
  colorClass,
}: {
  value: number;
  max?: number;
  colorClass: string;
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden mt-1.5">
      <div
        className={`h-full rounded-full transition-all duration-500 ${colorClass}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  valueColor,
  iconBg,
  iconColor,
  borderColor,
  progress,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  valueColor: string;
  iconBg: string;
  iconColor: string;
  borderColor: string;
  progress?: { value: number; max: number; colorClass: string };
}) {
  return (
    <div
      className={`bg-white border rounded-xl p-4 border-t-[3px] ${borderColor} shadow-sm`}
    >
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-lg ${iconBg}`}>
          <Icon className={`h-4 w-4 ${iconColor}`} />
        </div>
        <div className="flex-1 min-w-0">
          <p className={`text-2xl font-bold tabular-nums ${valueColor}`}>
            {value}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
          {progress && (
            <ProgressBar
              value={progress.value}
              max={progress.max}
              colorClass={progress.colorClass}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryKPIs({ diagnostics }: { diagnostics: DiagnosticsRead }) {
  const s = diagnostics.summary;

  const coverageColor =
    s.coverage_missing_required_slots > 0 ? "text-red-600" : "text-green-600";
  const coverageBorder =
    s.coverage_missing_required_slots > 0
      ? "border-t-red-400"
      : "border-t-green-400";
  const coverageIconBg =
    s.coverage_missing_required_slots > 0 ? "bg-red-100" : "bg-green-100";
  const coverageIconColor =
    s.coverage_missing_required_slots > 0
      ? "text-red-600"
      : "text-green-600";

  const hardColor =
    s.hard_issues_count > 0 ? "text-red-600" : "text-green-600";
  const hardBorder =
    s.hard_issues_count > 0 ? "border-t-red-400" : "border-t-green-400";
  const hardIconBg =
    s.hard_issues_count > 0 ? "bg-red-100" : "bg-green-100";
  const hardIconColor =
    s.hard_issues_count > 0 ? "text-red-600" : "text-green-600";

  const restColor =
    s.rest_violations > 0 ? "text-yellow-600" : "text-green-600";
  const restBorder =
    s.rest_violations > 0 ? "border-t-yellow-400" : "border-t-green-400";
  const restIconBg =
    s.rest_violations > 0 ? "bg-yellow-100" : "bg-green-100";
  const restIconColor =
    s.rest_violations > 0 ? "text-yellow-600" : "text-green-600";

  const fairnessValue = Math.round(s.fairness_index * 100);
  const fairnessColor =
    s.fairness_index >= 0.8
      ? "text-green-600"
      : s.fairness_index >= 0.5
        ? "text-yellow-600"
        : "text-red-600";
  const fairnessBorder =
    s.fairness_index >= 0.8
      ? "border-t-green-400"
      : s.fairness_index >= 0.5
        ? "border-t-yellow-400"
        : "border-t-red-400";
  const fairnessBarColor =
    s.fairness_index >= 0.8
      ? "bg-green-500"
      : s.fairness_index >= 0.5
        ? "bg-yellow-500"
        : "bg-red-500";

  const prefValue = Math.round(s.preference_fulfillment_pct);
  const prefColor =
    s.preference_fulfillment_pct >= 80
      ? "text-green-600"
      : s.preference_fulfillment_pct >= 50
        ? "text-yellow-600"
        : "text-red-600";
  const prefBorder =
    s.preference_fulfillment_pct >= 80
      ? "border-t-green-400"
      : s.preference_fulfillment_pct >= 50
        ? "border-t-yellow-400"
        : "border-t-red-400";
  const prefBarColor =
    s.preference_fulfillment_pct >= 80
      ? "bg-green-500"
      : s.preference_fulfillment_pct >= 50
        ? "bg-yellow-500"
        : "bg-red-500";

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
      <KpiCard
        icon={ShieldAlert}
        label="Coverage Gaps"
        value={s.coverage_missing_required_slots}
        valueColor={coverageColor}
        iconBg={coverageIconBg}
        iconColor={coverageIconColor}
        borderColor={coverageBorder}
      />
      <KpiCard
        icon={AlertOctagon}
        label="Hard Issues"
        value={s.hard_issues_count}
        valueColor={hardColor}
        iconBg={hardIconBg}
        iconColor={hardIconColor}
        borderColor={hardBorder}
      />
      <KpiCard
        icon={Clock}
        label="Rest Violations"
        value={s.rest_violations}
        valueColor={restColor}
        iconBg={restIconBg}
        iconColor={restIconColor}
        borderColor={restBorder}
      />
      <KpiCard
        icon={Scale}
        label="Fairness Index"
        value={`${fairnessValue}%`}
        valueColor={fairnessColor}
        iconBg="bg-indigo-100"
        iconColor="text-indigo-600"
        borderColor={fairnessBorder}
        progress={{
          value: fairnessValue,
          max: 100,
          colorClass: fairnessBarColor,
        }}
      />
      <KpiCard
        icon={Heart}
        label="Pref. Fulfillment"
        value={`${prefValue}%`}
        valueColor={prefColor}
        iconBg="bg-pink-100"
        iconColor="text-pink-600"
        borderColor={prefBorder}
        progress={{
          value: prefValue,
          max: 100,
          colorClass: prefBarColor,
        }}
      />
    </div>
  );
}

function FindingsSeverityGroup({
  severity,
  items,
  defaultExpanded,
  nameMap,
}: {
  severity: "critical" | "warning" | "info";
  items: DiagnosticsFindingRead[];
  defaultExpanded: boolean;
  nameMap: Map<number, string>;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const config = SEVERITY_CONFIG[severity];
  const Icon = config.icon;

  return (
    <div
      className={`border rounded-lg overflow-hidden ${config.border}`}
    >
      {/* Collapsible header */}
      <button
        type="button"
        className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-left ${config.headerBg} transition-colors hover:opacity-90`}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className={`h-4 w-4 ${config.headerText}`} />
        ) : (
          <ChevronRight className={`h-4 w-4 ${config.headerText}`} />
        )}
        <Icon className={`h-4 w-4 ${config.text}`} />
        <span className={`text-sm font-semibold ${config.headerText}`}>
          {config.label}
        </span>
        <span
          className={`ml-auto inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-full text-xs font-bold ${config.countBadge}`}
        >
          {items.length}
        </span>
      </button>

      {/* Findings */}
      {expanded && (
        <div className="divide-y divide-gray-100">
          {items.map((finding, i) => {
            const info = describeFinding(finding.code, finding.context || {}, nameMap);
            return (
              <div
                key={`${severity}-${i}`}
                className={`px-4 py-3 ${config.bg}`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <span className={`text-sm font-semibold ${config.text}`}>
                      {info.title}
                    </span>
                    <p className="text-sm text-gray-700 mt-0.5">
                      {info.description}
                    </p>
                    {info.tip && (
                      <p className="text-xs text-muted-foreground mt-1 italic">
                        {info.tip}
                      </p>
                    )}
                  </div>
                  {/* Context pills for quick scanning */}
                  <div className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
                    {finding.context?.day != null && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-white/80 border text-xs font-medium text-gray-600 tabular-nums">
                        Day {finding.context.day}
                      </span>
                    )}
                    {finding.context?.shift_type && (
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${
                          finding.context.shift_type === "onsite"
                            ? "bg-teal-100 text-teal-700"
                            : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {finding.context.shift_type}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FindingsList({
  findings,
  perDoctor,
}: {
  findings: DiagnosticsFindingRead[];
  perDoctor: DoctorDiagnosticsRead[];
}) {
  const nameMap = buildDoctorNameMap(perDoctor);

  if (findings.length === 0) {
    return (
      <div className="flex items-center gap-2 text-green-700 bg-green-50 border border-green-200 rounded-xl p-4 mb-6">
        <CheckCircle className="h-5 w-5" />
        <span className="text-sm font-medium">
          No issues found — schedule looks good
        </span>
      </div>
    );
  }

  // Group by severity
  const grouped: Record<string, DiagnosticsFindingRead[]> = {
    critical: [],
    warning: [],
    info: [],
  };
  for (const f of findings) {
    grouped[f.severity]?.push(f);
  }

  return (
    <div className="space-y-3 mb-6">
      {(["critical", "warning", "info"] as const).map((severity) => {
        const items = grouped[severity];
        if (items.length === 0) return null;

        return (
          <FindingsSeverityGroup
            key={severity}
            severity={severity}
            items={items}
            defaultExpanded={severity !== "info"}
            nameMap={nameMap}
          />
        );
      })}
    </div>
  );
}

function StarRating({ stars }: { stars: number | null }) {
  if (stars === null)
    return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          className={`h-3 w-3 ${
            i < stars
              ? "fill-yellow-400 text-yellow-400"
              : "text-gray-300"
          }`}
        />
      ))}
    </span>
  );
}

type SortField = "stars" | "name" | "onsite" | "oncall" | "rest" | "pref";

function SortIndicator({
  field,
  currentSort,
  currentDir,
}: {
  field: SortField;
  currentSort: SortField;
  currentDir: "asc" | "desc";
}) {
  if (field !== currentSort) {
    return <ArrowUpDown className="h-3 w-3 ml-1 opacity-30" />;
  }
  return currentDir === "asc" ? (
    <ArrowUp className="h-3 w-3 ml-1" />
  ) : (
    <ArrowDown className="h-3 w-3 ml-1" />
  );
}

function MiniProgressBar({
  value,
  colorClass,
}: {
  value: number;
  colorClass: string;
}) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className="w-12 h-1.5 bg-gray-200 rounded-full overflow-hidden inline-block ml-1.5 align-middle">
      <div
        className={`h-full rounded-full ${colorClass}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function DoctorBreakdownTable({
  perDoctor,
}: {
  perDoctor: DoctorDiagnosticsRead[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [sortBy, setSortBy] = useState<SortField>("stars");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  if (perDoctor.length === 0) return null;

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortDir(field === "name" ? "asc" : "asc");
    }
  };

  const multiplier = sortDir === "asc" ? 1 : -1;
  const sorted = [...perDoctor].sort((a, b) => {
    switch (sortBy) {
      case "stars":
        return ((a.ui_stars ?? 3) - (b.ui_stars ?? 3)) * multiplier;
      case "name":
        return a.display_name.localeCompare(b.display_name) * multiplier;
      case "onsite":
        return (a.assigned_onsite_total - b.assigned_onsite_total) * multiplier;
      case "oncall":
        return (a.assigned_oncall_total - b.assigned_oncall_total) * multiplier;
      case "rest":
        return (a.rest_violations - b.rest_violations) * multiplier;
      case "pref":
        return (
          (a.preference_fulfillment_pct - b.preference_fulfillment_pct) *
          multiplier
        );
      default:
        return 0;
    }
  });

  return (
    <div>
      <button
        className="flex items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground mb-3 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        Doctor Breakdown
        <span className="text-xs font-normal text-muted-foreground">
          ({perDoctor.length} doctors)
        </span>
      </button>

      {expanded && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50/80 border-b">
                <th
                  className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("name")}
                >
                  <span className="inline-flex items-center">
                    Doctor
                    <SortIndicator
                      field="name"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
                <th
                  className="px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("stars")}
                >
                  <span className="inline-flex items-center">
                    Rating
                    <SortIndicator
                      field="stars"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
                <th
                  className="px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("onsite")}
                >
                  <span className="inline-flex items-center">
                    Onsite
                    <SortIndicator
                      field="onsite"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
                <th
                  className="px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("oncall")}
                >
                  <span className="inline-flex items-center">
                    Oncall
                    <SortIndicator
                      field="oncall"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
                <th
                  className="px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("rest")}
                >
                  <span className="inline-flex items-center">
                    Rest Viol.
                    <SortIndicator
                      field="rest"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
                <th
                  className="px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none uppercase tracking-wider"
                  onClick={() => handleSort("pref")}
                >
                  <span className="inline-flex items-center">
                    Pref. %
                    <SortIndicator
                      field="pref"
                      currentSort={sortBy}
                      currentDir={sortDir}
                    />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map((doc) => {
                const prefPct = Math.round(doc.preference_fulfillment_pct);
                const prefColor =
                  prefPct >= 80
                    ? "text-green-600"
                    : prefPct >= 50
                      ? "text-yellow-600"
                      : "text-red-600";
                const prefBarColor =
                  prefPct >= 80
                    ? "bg-green-500"
                    : prefPct >= 50
                      ? "bg-yellow-500"
                      : "bg-red-500";

                return (
                  <tr
                    key={doc.doctor_id}
                    className="hover:bg-gray-50/80 transition-colors"
                  >
                    <td className="px-4 py-2.5 font-medium text-gray-800">
                      {doc.display_name}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <StarRating stars={doc.ui_stars} />
                    </td>
                    <td className="px-3 py-2.5 text-center tabular-nums font-medium">
                      {doc.assigned_onsite_total}
                    </td>
                    <td className="px-3 py-2.5 text-center tabular-nums font-medium">
                      {doc.assigned_oncall_total}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <span
                        className={`inline-flex items-center justify-center min-w-[24px] h-6 px-2 rounded-full text-xs font-bold ${
                          doc.rest_violations > 0
                            ? "bg-red-100 text-red-700"
                            : "bg-green-100 text-green-700"
                        }`}
                      >
                        {doc.rest_violations}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <span className={`text-sm font-semibold ${prefColor}`}>
                        {prefPct}%
                      </span>
                      <MiniProgressBar
                        value={prefPct}
                        colorClass={prefBarColor}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export const DiagnosticsPanel = ({ diagnostics }: DiagnosticsPanelProps) => {
  if (!diagnostics) return null;

  const findings = diagnostics.details?.findings || [];
  const perDoctor = diagnostics.details?.per_doctor || [];

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-lg">Diagnostics</CardTitle>
      </CardHeader>
      <CardContent>
        <SummaryKPIs diagnostics={diagnostics} />
        <FindingsList findings={findings} perDoctor={perDoctor} />
        <DoctorBreakdownTable perDoctor={perDoctor} />
      </CardContent>
    </Card>
  );
};
