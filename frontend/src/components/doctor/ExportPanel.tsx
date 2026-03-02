import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "../ui/button";
import {
  Download,
  FileText,
  FileSpreadsheet,
  Calendar,
  Loader2,
  SlidersHorizontal,
  User,
  ArrowDownToLine,
  ChevronDown,
  Link2,
  Check,
  RefreshCw,
} from "lucide-react";
import { schedulesApi } from "../../services/api";

interface ExportPanelProps {
  year: number;
  month: number;
  viewMode: "my-schedule" | "team-schedule";
  highlightedDoctorId?: number | null;
  highlightedDoctorName?: string | null;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}

type ShiftFilter = "all" | "onsite" | "oncall";
type RoleFilter = "all" | "specialist" | "resident";

const SHIFT_LABELS: Record<ShiftFilter, string> = {
  all: "All shifts",
  onsite: "On-site",
  oncall: "On-call",
};

const ROLE_LABELS: Record<RoleFilter, string> = {
  all: "All roles",
  specialist: "Specialists",
  resident: "Residents",
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const ExportPanel = ({
  year,
  month,
  viewMode,
  highlightedDoctorId,
  highlightedDoctorName,
}: ExportPanelProps) => {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [shiftFilter, setShiftFilter] = useState<ShiftFilter>("all");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const panelRef = useRef<HTMLDivElement>(null);

  // Calendar subscription state (My Schedule only)
  const [calendarToken, setCalendarToken] = useState<string | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const isTeam = viewMode === "team-schedule";
  const pad = String(month).padStart(2, "0");
  const hasFilters =
    isTeam &&
    (highlightedDoctorId != null ||
      shiftFilter !== "all" ||
      roleFilter !== "all");

  // Close panel when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };

    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  // Reset filters when switching away from team mode
  useEffect(() => {
    if (!isTeam) {
      setShiftFilter("all");
      setRoleFilter("all");
    }
  }, [isTeam]);

  // Fetch calendar token lazily when panel opens (both modes need it)
  useEffect(() => {
    if (open && calendarToken === null && !tokenLoading) {
      setTokenLoading(true);
      schedulesApi
        .getCalendarToken()
        .then((res) => setCalendarToken(res.token))
        .catch(() => {
          // Token fetch failed — subscription UI will be hidden
        })
        .finally(() => setTokenLoading(false));
    }
  }, [open, calendarToken, tokenLoading]);

  // Build subscription URLs from token
  const personalFeedUrl = calendarToken
    ? `${API_BASE}/api/v1/calendars/${calendarToken}.ics`
    : null;
  const teamFeedUrl = calendarToken
    ? `${API_BASE}/api/v1/calendars/${calendarToken}/team.ics`
    : null;
  const feedUrl = isTeam ? teamFeedUrl : personalFeedUrl;
  const webcalUrl = feedUrl
    ? feedUrl.replace(/^https?:\/\//, "webcal://")
    : null;
  const googleUrl = webcalUrl
    ? `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcalUrl)}`
    : null;

  const handleExport = useCallback(
    async (format: "xlsx" | "pdf" | "ics") => {
      if (downloading) return;
      setDownloading(format);
      try {
        let blob: Blob;
        let filename: string;

        if (isTeam) {
          const filters: {
            doctor_ids?: string;
            shift_type?: "onsite" | "oncall";
            role?: "specialist" | "resident";
          } = {};
          if (highlightedDoctorId != null) {
            filters.doctor_ids = String(highlightedDoctorId);
          }
          if (shiftFilter !== "all") {
            filters.shift_type = shiftFilter;
          }
          if (roleFilter !== "all") {
            filters.role = roleFilter;
          }
          blob = await schedulesApi.exportTeamSchedule(
            year,
            month,
            format,
            filters,
          );
          filename = `team-schedule-${year}-${pad}.${format}`;
        } else {
          blob = await schedulesApi.exportMySchedule(year, month, format);
          filename = `schedule-${year}-${pad}.${format}`;
        }

        triggerDownload(blob, filename);
        setOpen(false);
      } catch {
        alert(
          "Export failed. Make sure a published schedule exists for this month.",
        );
      } finally {
        setDownloading(null);
      }
    },
    [
      year,
      month,
      downloading,
      isTeam,
      pad,
      highlightedDoctorId,
      shiftFilter,
      roleFilter,
    ],
  );

  const handleCopyUrl = useCallback(async () => {
    if (!feedUrl) return;
    try {
      await navigator.clipboard.writeText(feedUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select text from a temporary input
      const input = document.createElement("input");
      input.value = feedUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [feedUrl]);

  const handleRegenerateToken = useCallback(async () => {
    if (tokenLoading) return;
    setTokenLoading(true);
    try {
      const res = await schedulesApi.regenerateCalendarToken();
      setCalendarToken(res.token);
    } catch {
      alert("Failed to regenerate token. Please try again.");
    } finally {
      setTokenLoading(false);
    }
  }, [tokenLoading]);

  const isLoading = (format: string) => downloading === format;

  const activeFilterCount =
    (highlightedDoctorId != null ? 1 : 0) +
    (shiftFilter !== "all" ? 1 : 0) +
    (roleFilter !== "all" ? 1 : 0);

  return (
    <div className="relative" ref={panelRef}>
      {/* Trigger button */}
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(!open)}
        className={`gap-2 transition-all duration-200 ${
          open
            ? "bg-blue-50 border-blue-200 text-blue-700 shadow-sm"
            : "hover:bg-gray-50"
        }`}
      >
        <ArrowDownToLine className="h-3.5 w-3.5" />
        <span>Export</span>
        <ChevronDown
          className={`h-3 w-3 opacity-50 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </Button>

      {/* Dropdown panel */}
      {open && (
        <div
          className="absolute right-0 bottom-full mb-2 z-20 min-w-[260px] overflow-hidden
            rounded-xl border border-gray-200/80 bg-white
            shadow-[0_8px_30px_rgb(0,0,0,0.08),0_2px_8px_rgb(0,0,0,0.04)]
            animate-in fade-in slide-in-from-bottom-2 duration-150"
        >
          {/* Header */}
          <div className="px-4 pt-3.5 pb-2.5">
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center h-5 w-5 rounded-md bg-blue-50">
                <Download className="h-3 w-3 text-blue-600" />
              </div>
              <span className="text-xs font-semibold tracking-wide text-gray-400 uppercase">
                Export & Sync
              </span>
            </div>
          </div>

          {/* Filters section — only in team mode */}
          {isTeam && (
            <div className="mx-3 mb-2.5 rounded-lg border border-gray-100 bg-gray-50/70">
              <div className="px-3 pt-2.5 pb-2">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <SlidersHorizontal className="h-3 w-3 text-gray-400" />
                    <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">
                      Filters
                    </span>
                  </div>
                  {hasFilters && (
                    <span className="inline-flex items-center justify-center h-4 min-w-[16px] px-1 rounded-full bg-blue-600 text-[10px] font-semibold text-white tabular-nums">
                      {activeFilterCount}
                    </span>
                  )}
                </div>

                {/* Doctor filter indicator */}
                {highlightedDoctorId != null && (
                  <div className="flex items-center gap-1.5 mb-2 px-2 py-1 rounded-md bg-blue-50 border border-blue-100">
                    <User className="h-3 w-3 text-blue-500 flex-shrink-0" />
                    <span className="text-xs text-blue-700 font-medium truncate">
                      {highlightedDoctorName || `Doctor #${highlightedDoctorId}`}
                    </span>
                  </div>
                )}

                {/* Shift type filter */}
                <div className="flex gap-1 mb-1.5">
                  {(["all", "onsite", "oncall"] as const).map((v) => (
                    <button
                      key={v}
                      onClick={() => setShiftFilter(v)}
                      className={`px-2.5 py-1 text-[11px] font-medium rounded-md border transition-all duration-150 ${
                        shiftFilter === v
                          ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                          : "bg-white border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700"
                      }`}
                    >
                      {SHIFT_LABELS[v]}
                    </button>
                  ))}
                </div>

                {/* Role filter */}
                <div className="flex gap-1">
                  {(["all", "specialist", "resident"] as const).map((v) => (
                    <button
                      key={v}
                      onClick={() => setRoleFilter(v)}
                      className={`px-2.5 py-1 text-[11px] font-medium rounded-md border transition-all duration-150 ${
                        roleFilter === v
                          ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                          : "bg-white border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700"
                      }`}
                    >
                      {ROLE_LABELS[v]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Active filters badge */}
              {hasFilters && (
                <div className="px-3 py-1.5 border-t border-gray-100 bg-amber-50/60">
                  <span className="text-[11px] font-medium text-amber-700">
                    Export will include filtered results only
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Download section */}
          <div className="px-1.5 pb-1">
            {/* Section label */}
            <div className="px-2.5 pt-0.5 pb-1.5">
              <span className="text-[10px] font-semibold tracking-wider text-gray-300 uppercase">
                Download
              </span>
            </div>

            <button
              onClick={() => handleExport("pdf")}
              disabled={downloading !== null}
              className="group w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors duration-100
                hover:bg-gray-50 active:bg-gray-100 disabled:opacity-40 disabled:pointer-events-none"
            >
              <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-red-50 group-hover:bg-red-100 transition-colors">
                <FileText className="h-3.5 w-3.5 text-red-500" />
              </div>
              <div className="flex-1 min-w-0">
                <span className="font-medium text-gray-700 text-[13px]">PDF Document</span>
              </div>
              {isLoading("pdf") ? (
                <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin flex-shrink-0" />
              ) : (
                <Download className="h-3.5 w-3.5 text-gray-300 group-hover:text-gray-400 transition-colors flex-shrink-0" />
              )}
            </button>

            <button
              onClick={() => handleExport("xlsx")}
              disabled={downloading !== null}
              className="group w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors duration-100
                hover:bg-gray-50 active:bg-gray-100 disabled:opacity-40 disabled:pointer-events-none"
            >
              <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-emerald-50 group-hover:bg-emerald-100 transition-colors">
                <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />
              </div>
              <div className="flex-1 min-w-0">
                <span className="font-medium text-gray-700 text-[13px]">Excel Spreadsheet</span>
              </div>
              {isLoading("xlsx") ? (
                <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin flex-shrink-0" />
              ) : (
                <Download className="h-3.5 w-3.5 text-gray-300 group-hover:text-gray-400 transition-colors flex-shrink-0" />
              )}
            </button>
          </div>

          {/* Calendar sync section */}
          <div className="px-1.5 pb-2">
            <div className="mx-1.5 border-t border-gray-100 mb-1" />

            <div className="px-2.5 pt-1.5 pb-1.5">
              <span className="text-[10px] font-semibold tracking-wider text-gray-300 uppercase">
                Calendar Sync
              </span>
            </div>

            {calendarToken ? (
              <>
                {/* Subscription buttons (both modes) */}
                <button
                  onClick={() => {
                    if (googleUrl) window.open(googleUrl, "_blank");
                  }}
                  disabled={!googleUrl}
                  className="group w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors duration-100
                    hover:bg-gray-50 active:bg-gray-100 disabled:opacity-40 disabled:pointer-events-none"
                >
                  <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-blue-50 group-hover:bg-blue-100 transition-colors">
                    <Calendar className="h-3.5 w-3.5 text-blue-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-gray-700 text-[13px]">Google Calendar</span>
                    <span className="block text-[10px] text-gray-400">Subscribe &mdash; auto-updates</span>
                  </div>
                </button>

                <button
                  onClick={() => {
                    if (webcalUrl) window.location.href = webcalUrl;
                  }}
                  disabled={!webcalUrl}
                  className="group w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors duration-100
                    hover:bg-gray-50 active:bg-gray-100 disabled:opacity-40 disabled:pointer-events-none"
                >
                  <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-gray-100 group-hover:bg-gray-200/70 transition-colors">
                    <Calendar className="h-3.5 w-3.5 text-gray-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-gray-700 text-[13px]">Apple Calendar</span>
                    <span className="block text-[10px] text-gray-400">Subscribe &mdash; auto-updates</span>
                  </div>
                </button>

                <button
                  onClick={handleCopyUrl}
                  className="group w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors duration-100
                    hover:bg-gray-50 active:bg-gray-100"
                >
                  <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-violet-50 group-hover:bg-violet-100 transition-colors">
                    {copied ? (
                      <Check className="h-3.5 w-3.5 text-green-600" />
                    ) : (
                      <Link2 className="h-3.5 w-3.5 text-violet-600" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-gray-700 text-[13px]">
                      {copied ? "Copied!" : "Copy Feed URL"}
                    </span>
                    <span className="block text-[10px] text-gray-400">For other calendar apps</span>
                  </div>
                </button>

                {/* Regenerate token */}
                <div className="mx-1.5 border-t border-gray-100 mt-1 mb-1" />
                <button
                  onClick={handleRegenerateToken}
                  disabled={tokenLoading}
                  className="group w-full flex items-center gap-3 px-3 py-1.5 rounded-lg text-sm text-left transition-colors duration-100
                    hover:bg-gray-50 active:bg-gray-100 disabled:opacity-40 disabled:pointer-events-none"
                >
                  <div className="flex items-center justify-center h-6 w-6 rounded-md bg-gray-50 group-hover:bg-gray-100 transition-colors">
                    {tokenLoading ? (
                      <Loader2 className="h-3 w-3 text-gray-400 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3 w-3 text-gray-400" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-[11px] text-gray-400">Reset subscription link</span>
                  </div>
                </button>
              </>
            ) : tokenLoading ? (
              <div className="flex items-center justify-center py-3">
                <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
};
