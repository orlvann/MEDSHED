import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  ScheduleGrid,
  ScheduleCalendarView,
  DiagnosticsPanel,
  PublishModal,
} from "../../components/admin/schedules";
import { schedulesApi } from "../../services/api";
import type {
  SchedulesPeriodViewRead,
  Assignment,
  ShiftType,
  DiagnosticsRead,
  AcceptedException,
} from "../../types";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Undo2,
  Redo2,
  Save,
  Send,
  Calendar,
  List,
  CalendarDays,
  CheckCircle2,
} from "lucide-react";

/** Extract human-readable message from backend error response. */
function extractErrorMessage(err: any, fallback: string): string {
  const detail = err.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.detail && typeof detail.detail === "string") return detail.detail;
  return fallback;
}

export const SchedulesManagement = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Period selection — read from URL params or default to next month
  const now = new Date();
  const defaultMonth = now.getMonth() + 2; // getMonth() is 0-based, +2 = next month
  const defaultYear = defaultMonth > 12 ? now.getFullYear() + 1 : now.getFullYear();
  const defaultMonthNormalized = defaultMonth > 12 ? 1 : defaultMonth;
  const [year, setYear] = useState(
    Number(searchParams.get("year")) || defaultYear
  );
  const [month, setMonth] = useState(
    Number(searchParams.get("month")) || defaultMonthNormalized
  );

  // Data
  const [periodView, setPeriodView] =
    useState<SchedulesPeriodViewRead | null>(null);
  const [viewMode, setViewMode] = useState<"draft" | "published">("draft");
  const [workingAssignments, setWorkingAssignments] = useState<Assignment[]>(
    []
  );
  const [diagnostics, setDiagnostics] = useState<DiagnosticsRead | null>(null);
  const [lockVersion, setLockVersion] = useState<number | null>(null);

  // Display mode
  const [displayMode, setDisplayMode] = useState<"list" | "calendar">("list");

  // UI states
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  // Autosave debounce
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch period view
  const fetchPeriodView = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await schedulesApi.getPeriodView(year, month);
      setPeriodView(data);
      setViewMode(data.view.default_mode);
      setWorkingAssignments(data.working.assignments);
      setLockVersion(data.working.lock_version);
      setDiagnostics(data.diagnostics);
      setIsDirty(false);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setPeriodView(null);
        setDiagnostics(null);
        setWorkingAssignments([]);
      } else {
        setError(
          extractErrorMessage(err, "Failed to load schedule data")
        );
      }
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    fetchPeriodView();
  }, [fetchPeriodView]);

  // Month navigation
  const handlePrevMonth = () => {
    if (month === 1) {
      setYear(year - 1);
      setMonth(12);
    } else {
      setMonth(month - 1);
    }
  };

  const handleNextMonth = () => {
    if (month === 12) {
      setYear(year + 1);
      setMonth(1);
    } else {
      setMonth(month + 1);
    }
  };

  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  // Autosave working buffer
  const saveWorking = useCallback(
    async (assignments: Assignment[]) => {
      try {
        setSaving(true);
        const ack = await schedulesApi.saveWorking(year, month, {
          assignments,
          if_match_lock_version: lockVersion,
        });
        setLockVersion(ack.lock_version);
        setIsDirty(false);
      } catch (err: any) {
        console.error("Autosave failed:", err);
        setError(extractErrorMessage(err, "Failed to save changes"));
      } finally {
        setSaving(false);
      }
    },
    [year, month, lockVersion]
  );

  const debouncedSave = useCallback(
    (assignments: Assignment[]) => {
      if (autosaveTimer.current) {
        clearTimeout(autosaveTimer.current);
      }
      autosaveTimer.current = setTimeout(() => {
        saveWorking(assignments);
      }, 1500);
    },
    [saveWorking]
  );

  // Handle assignment change from grid
  const handleAssignmentChange = useCallback(
    (day: number, shiftType: ShiftType, newDoctorId: number) => {
      setWorkingAssignments((prev) => {
        const updated = prev.filter(
          (a) => !(a.day === day && a.shift_type === shiftType)
        );
        updated.push({ day, shift_type: shiftType, doctor_id: newDoctorId });
        debouncedSave(updated);
        setIsDirty(true);
        return updated;
      });
    },
    [debouncedSave]
  );

  // Save checkpoint
  const handleCheckpoint = async () => {
    // Flush any pending autosave first
    if (autosaveTimer.current) {
      clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    }
    if (isDirty) {
      await saveWorking(workingAssignments);
    }

    try {
      setSaving(true);
      setError(null);
      const result = await schedulesApi.checkpoint(year, month);
      setPeriodView((prev) =>
        prev ? { ...prev, draft: result.draft } : prev
      );
      setDiagnostics(result.diagnostics);
      setIsDirty(false);
    } catch (err: any) {
      setError(extractErrorMessage(err, "Failed to create checkpoint"));
    } finally {
      setSaving(false);
    }
  };

  // Undo
  const handleUndo = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await schedulesApi.revertDraft(year, month);
      setPeriodView((prev) =>
        prev
          ? { ...prev, draft: result.draft, working: result.working }
          : prev
      );
      setWorkingAssignments(result.working.assignments);
      setLockVersion(result.working.lock_version);
      setDiagnostics(result.diagnostics);
      setIsDirty(false);
    } catch (err: any) {
      setError(extractErrorMessage(err, "Undo failed"));
    } finally {
      setSaving(false);
    }
  };

  // Redo
  const handleRedo = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await schedulesApi.redoDraft(year, month);
      setPeriodView((prev) =>
        prev
          ? { ...prev, draft: result.draft, working: result.working }
          : prev
      );
      setWorkingAssignments(result.working.assignments);
      setLockVersion(result.working.lock_version);
      setDiagnostics(result.diagnostics);
      setIsDirty(false);
    } catch (err: any) {
      setError(extractErrorMessage(err, "Redo failed"));
    } finally {
      setSaving(false);
    }
  };

  // Publish
  const handlePublish = async (
    force: boolean,
    note: string,
    acceptedExceptions: AcceptedException[]
  ) => {
    try {
      setPublishing(true);
      setError(null);
      const result = await schedulesApi.publish(year, month, {
        force,
        note: note || undefined,
        accepted_exceptions: acceptedExceptions,
      });
      setPeriodView((prev) =>
        prev
          ? {
              ...prev,
              published: result.published,
              view: { ...prev.view, toggle_available: true },
            }
          : prev
      );
      setShowPublishModal(false);
      setViewMode("published");
    } catch (err: any) {
      setError(extractErrorMessage(err, "Publish failed"));
    } finally {
      setPublishing(false);
    }
  };

  // Published undo/redo
  const handlePublishedUndo = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await schedulesApi.revertPublished(year, month);
      setPeriodView((prev) =>
        prev ? { ...prev, published: result.published } : prev
      );
    } catch (err: any) {
      setError(extractErrorMessage(err, "Published undo failed"));
    } finally {
      setSaving(false);
    }
  };

  const handlePublishedRedo = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await schedulesApi.redoPublished(year, month);
      setPeriodView((prev) =>
        prev ? { ...prev, published: result.published } : prev
      );
    } catch (err: any) {
      setError(extractErrorMessage(err, "Published redo failed"));
    } finally {
      setSaving(false);
    }
  };

  // Determine current view data
  const isDraftMode = viewMode === "draft";
  const canToggle = periodView?.view.toggle_available ?? false;
  const draft = periodView?.draft;
  const published = periodView?.published;

  const currentAssignments = isDraftMode
    ? workingAssignments
    : published?.payload?.assignments || [];
  const currentSnapshot = isDraftMode
    ? periodView?.working.inputs_snapshot || null
    : published?.payload?.inputs_snapshot || null;
  const currentParticipants = isDraftMode
    ? periodView?.working.participant_doctor_ids || []
    : published?.payload?.participant_doctor_ids || [];

  const canUndo = isDraftMode
    ? draft?.can_undo ?? false
    : published?.can_undo ?? false;
  const canRedo = isDraftMode
    ? draft?.can_redo ?? false
    : published?.can_redo ?? false;

  const hasSchedule = periodView?.working.exists ?? false;
  const isPublished = (published?.version_id ?? null) !== null;
  const publicationsCount = published?.publications_count ?? 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminHeader />
      <main className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/admin")}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <h2 className="text-3xl font-bold">Schedules</h2>
          </div>
        </div>

        {/* Month/Year Selector */}
        <Card className="mb-6">
          <CardContent className="pt-6">
            <div className="flex items-center justify-center gap-4">
              <Button
                variant="outline"
                size="sm"
                onClick={handlePrevMonth}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="text-xl font-semibold min-w-[180px] text-center">
                {monthName} {year}
              </div>
              <Button variant="outline" size="sm" onClick={handleNextMonth}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Error display */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
            {error}
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className="space-y-4">
            <div className="h-12 bg-gray-200 rounded animate-pulse" />
            <div className="h-64 bg-gray-200 rounded animate-pulse" />
          </div>
        )}

        {/* Empty state */}
        {!loading && !hasSchedule && (
          <Card className="mb-6">
            <CardContent className="py-12 text-center">
              <Calendar className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">
                No schedule generated
              </h3>
              <p className="text-muted-foreground mb-4">
                No schedule exists for {monthName} {year}. Generate one first.
              </p>
              <Button
                onClick={() =>
                  navigate(`/admin/generate?year=${year}&month=${month}`)
                }
              >
                Generate Schedule
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Schedule content */}
        {!loading && hasSchedule && (
          <>
            {/* Action Bar */}
            <Card className="mb-6">
              <CardContent className="py-3">
                <div className="flex items-center justify-between flex-wrap gap-3">
                  {/* View toggle */}
                  <div className="flex items-center gap-2">
                    <div className="inline-flex rounded-md border">
                      <button
                        className={`px-3 py-1.5 text-sm font-medium rounded-l-md transition-colors ${
                          isDraftMode
                            ? "bg-primary text-primary-foreground"
                            : "hover:bg-gray-100"
                        }`}
                        onClick={() => setViewMode("draft")}
                      >
                        Draft
                      </button>
                      <button
                        className={`px-3 py-1.5 text-sm font-medium rounded-r-md transition-colors flex items-center gap-1.5 ${
                          !isDraftMode
                            ? "bg-primary text-primary-foreground"
                            : canToggle
                              ? "hover:bg-gray-100"
                              : "opacity-50 cursor-not-allowed"
                        }`}
                        onClick={() => canToggle && setViewMode("published")}
                        disabled={!canToggle}
                      >
                        {isPublished && (
                          <CheckCircle2 className={`h-3.5 w-3.5 ${!isDraftMode ? "text-primary-foreground" : "text-green-600"}`} />
                        )}
                        Published
                      </button>
                    </div>
                    {/* List / Calendar toggle */}
                    <div className="inline-flex rounded-md border ml-2">
                      <button
                        className={`p-1.5 rounded-l-md transition-colors ${
                          displayMode === "list"
                            ? "bg-gray-200 text-gray-900"
                            : "hover:bg-gray-100 text-gray-500"
                        }`}
                        onClick={() => setDisplayMode("list")}
                        title="List view"
                      >
                        <List className="h-4 w-4" />
                      </button>
                      <button
                        className={`p-1.5 rounded-r-md transition-colors ${
                          displayMode === "calendar"
                            ? "bg-gray-200 text-gray-900"
                            : "hover:bg-gray-100 text-gray-500"
                        }`}
                        onClick={() => setDisplayMode("calendar")}
                        title="Calendar view"
                      >
                        <CalendarDays className="h-4 w-4" />
                      </button>
                    </div>

                    {isDirty && (
                      <span className="text-xs text-muted-foreground">
                        {saving ? "Saving..." : "Unsaved changes"}
                      </span>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {/* Undo/Redo */}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={
                        isDraftMode ? handleUndo : handlePublishedUndo
                      }
                      disabled={!canUndo || saving}
                      title="Undo"
                    >
                      <Undo2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={
                        isDraftMode ? handleRedo : handlePublishedRedo
                      }
                      disabled={!canRedo || saving}
                      title="Redo"
                    >
                      <Redo2 className="h-4 w-4" />
                    </Button>

                    {/* Save checkpoint (draft only) */}
                    {isDraftMode && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleCheckpoint}
                        disabled={saving}
                      >
                        <Save className="h-4 w-4 mr-2" />
                        Save Checkpoint
                      </Button>
                    )}

                    {/* Publish (draft only) */}
                    {isDraftMode && (
                      <Button
                        size="sm"
                        onClick={() => setShowPublishModal(true)}
                        disabled={saving}
                      >
                        <Send className="h-4 w-4 mr-2" />
                        Publish
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Published status banner */}
            {isPublished && (
              <div className="mb-4 flex items-center gap-2 px-4 py-2.5 bg-green-50 border border-green-200 rounded-lg">
                <CheckCircle2 className="h-4 w-4 text-green-600 flex-shrink-0" />
                <span className="text-sm text-green-800 font-medium">
                  Published
                </span>
                {publicationsCount > 1 && (
                  <span className="text-xs text-green-600">
                    (v{publicationsCount})
                  </span>
                )}
                {!isDraftMode && (
                  <span className="text-xs text-green-600 ml-auto">
                    Viewing published version
                  </span>
                )}
                {isDraftMode && (
                  <span className="text-xs text-muted-foreground ml-auto">
                    Editing draft — published version available
                  </span>
                )}
              </div>
            )}

            {/* Schedule Grid / Calendar */}
            {displayMode === "list" ? (
              <ScheduleGrid
                year={year}
                month={month}
                assignments={currentAssignments}
                inputsSnapshot={currentSnapshot}
                participantDoctorIds={currentParticipants}
                readOnly={!isDraftMode}
                onAssignmentChange={handleAssignmentChange}
              />
            ) : (
              <ScheduleCalendarView
                year={year}
                month={month}
                assignments={currentAssignments}
                inputsSnapshot={currentSnapshot}
                participantDoctorIds={currentParticipants}
                readOnly={!isDraftMode}
                onAssignmentChange={handleAssignmentChange}
              />
            )}

            {/* Diagnostics Panel */}
            <DiagnosticsPanel diagnostics={diagnostics} />
          </>
        )}
      </main>

      {/* Publish Modal */}
      <PublishModal
        open={showPublishModal}
        onClose={() => setShowPublishModal(false)}
        onPublish={handlePublish}
        diagnostics={diagnostics}
        publishing={publishing}
      />
    </div>
  );
};
