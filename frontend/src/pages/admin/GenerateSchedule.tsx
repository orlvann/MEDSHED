import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  ActiveDoctorsList,
  AvailabilityHeatmap,
  DayDrilldownModal,
  IgnoreGapsModal,
  SolverErrorPanel,
} from "../../components/admin/generate";
import type {
  SolverErrorData,
  HeadCommitmentResolution,
} from "../../components/admin/generate";
import { doctorsApi, availabilityApi, schedulesApi, preferencesApi } from "../../services/api";
import type {
  Doctor,
  AvailabilityOverviewRead,
  IgnoredSlot,
  PreferencesSummaryRead,
} from "../../types";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Info,
  Sparkles,
} from "lucide-react";

/** Known 409 error codes from the generate endpoint. */
const SOLVER_ERROR_CODES = new Set([
  "generate_requires_ignore",
  "generate_requires_head_resolution",
  "generate_infeasible",
]);

/** Extract human-readable message from backend error response. */
function parseApiError(err: any): {
  message: string;
  solverError: SolverErrorData | null;
} {
  const detail = err.response?.data?.detail;

  if (typeof detail === "object" && detail?.code && SOLVER_ERROR_CODES.has(detail.code)) {
    return {
      message: detail.detail || detail.code,
      solverError: {
        code: detail.code,
        detail: detail.detail || detail.code,
        context: detail.context || {},
      },
    };
  }

  const message =
    typeof detail === "string"
      ? detail
      : detail?.detail || "An unexpected error occurred";

  return { message, solverError: null };
}

export const GenerateSchedule = () => {
  const navigate = useNavigate();

  // Period selection — default to next month
  const now = new Date();
  const _defaultMonth = now.getMonth() + 2; // getMonth() is 0-based, +2 = next month
  const [year, setYear] = useState(_defaultMonth > 12 ? now.getFullYear() + 1 : now.getFullYear());
  const [month, setMonth] = useState(_defaultMonth > 12 ? 1 : _defaultMonth);

  // Data
  const [activeDoctors, setActiveDoctors] = useState<Doctor[]>([]);
  const [overview, setOverview] = useState<AvailabilityOverviewRead | null>(
    null,
  );
  const [prefSummary, setPrefSummary] = useState<PreferencesSummaryRead | null>(
    null,
  );

  // Loading states
  const [loadingDoctors, setLoadingDoctors] = useState(true);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Error states
  const [error, setError] = useState<string | null>(null);
  const [solverError, setSolverError] = useState<SolverErrorData | null>(null);

  // Modal states
  const [drilldownDay, setDrilldownDay] = useState<number | null>(null);
  const [showIgnoreModal, setShowIgnoreModal] = useState(false);

  // Fetch active doctors
  const fetchActiveDoctors = useCallback(async () => {
    try {
      setLoadingDoctors(true);
      const response = await doctorsApi.list({
        is_active: "true",
        size: 100,
      });
      setActiveDoctors(response.items);
    } catch (err: any) {
      console.error("Failed to load doctors:", err);
      setError("Failed to load active doctors");
    } finally {
      setLoadingDoctors(false);
    }
  }, []);

  // Fetch availability overview + preferences summary in parallel
  const fetchOverview = useCallback(async () => {
    try {
      setLoadingOverview(true);
      setError(null);
      setSolverError(null);
      const [data, summary] = await Promise.all([
        availabilityApi.getOverview(year, month),
        preferencesApi.getSummary(year, month).catch(() => null),
      ]);
      setOverview(data);
      setPrefSummary(summary);
    } catch (err: any) {
      console.error("Failed to load availability:", err);
      const { message } = parseApiError(err);
      setError(message);
    } finally {
      setLoadingOverview(false);
    }
  }, [year, month]);

  // Initial load
  useEffect(() => {
    fetchActiveDoctors();
  }, [fetchActiveDoctors]);

  // Load overview when period changes
  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

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

  // Check if we can go to previous month (not before current month)
  const canGoPrev = () => {
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    return year > currentYear || (year === currentYear && month > currentMonth);
  };

  // Get critical and alert days
  const criticalDays =
    overview?.days.filter((d) => d.risk === "critical") || [];
  const alertDays = overview?.days.filter((d) => d.risk === "alert") || [];
  const hasCriticalDays = criticalDays.length > 0;
  const hasAlertDays = alertDays.length > 0;

  // Extract days with solver errors to highlight on the heatmap
  const solverErrorDays = useMemo(() => {
    if (!solverError?.context) return undefined;
    const ctx = solverError.context;
    const days = new Set<number>();

    // Extract from issues_sample (generate_requires_ignore & generate_infeasible)
    if (Array.isArray(ctx.issues_sample)) {
      for (const issue of ctx.issues_sample) {
        if (typeof issue.day === "number") days.add(issue.day);
      }
    }

    // Extract from head_commitment_conflicts (generate_requires_head_resolution)
    if (Array.isArray(ctx.head_commitment_conflicts)) {
      for (const conflict of ctx.head_commitment_conflicts) {
        if (typeof conflict.day === "number") days.add(conflict.day);
      }
    }

    return days.size > 0 ? days : undefined;
  }, [solverError]);

  // Extract solver issues for a specific day (for the drilldown modal)
  const getSolverIssuesForDay = (day: number) => {
    if (!solverError?.context) return undefined;
    const ctx = solverError.context;
    const issues: { code: string; message: string }[] = [];

    if (Array.isArray(ctx.issues_sample)) {
      for (const issue of ctx.issues_sample) {
        if (issue.day === day) {
          issues.push({ code: issue.code, message: issue.message });
        }
      }
    }

    if (Array.isArray(ctx.head_commitment_conflicts)) {
      for (const conflict of ctx.head_commitment_conflicts) {
        if (conflict.day === day) {
          issues.push({
            code: "head_commitment_conflict",
            message: `Head doctor conflict for ${conflict.shift_type}`,
          });
        }
      }
    }

    return issues.length > 0 ? issues : undefined;
  };

  // Handle generate button click
  const handleGenerateClick = () => {
    if (hasCriticalDays) {
      setShowIgnoreModal(true);
    } else {
      handleGenerate([]);
    }
  };

  // Generate schedule (core call)
  const handleGenerate = async (
    ignoreSlots: IgnoredSlot[],
    headResolutions: HeadCommitmentResolution[] = [],
  ) => {
    try {
      setGenerating(true);
      setError(null);
      setSolverError(null);

      const body: any = {
        year,
        month,
        participant_doctor_ids: activeDoctors.map((d) => d.id),
        ignore_slots: ignoreSlots,
      };
      if (headResolutions.length > 0) {
        body.head_commitment_resolutions = headResolutions;
      }

      await schedulesApi.generate(body);

      // Navigate to schedules page on success
      navigate(`/admin/schedules?year=${year}&month=${month}`);
    } catch (err: any) {
      console.error("Failed to generate schedule:", err);
      const { message, solverError: se } = parseApiError(err);

      if (se) {
        setSolverError(se);
        setError(null);
      } else {
        setError(message);
        setSolverError(null);
      }

      setShowIgnoreModal(false);
    } finally {
      setGenerating(false);
    }
  };

  // Handle accept from availability-based ignore modal
  const handleAcceptIgnore = (ignoreSlots: IgnoredSlot[]) => {
    handleGenerate(ignoreSlots);
  };

  // Handle retry from solver error panel: ignore
  const handleRetryWithIgnore = (ignoreSlots: IgnoredSlot[]) => {
    handleGenerate(ignoreSlots);
  };

  // Handle retry from solver error panel: head resolution
  const handleRetryWithHeadResolution = (
    resolutions: HeadCommitmentResolution[],
    ignoreSlots: IgnoredSlot[],
  ) => {
    handleGenerate(ignoreSlots, resolutions);
  };

  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  const isLoading = loadingDoctors || loadingOverview;

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
            <h2 className="text-3xl font-bold">Generate New Schedule</h2>
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
                disabled={!canGoPrev()}
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

        {/* Active Doctors List */}
        <ActiveDoctorsList doctors={activeDoctors} loading={loadingDoctors} />

        {/* Preferences Warnings */}
        {!isLoading && prefSummary && prefSummary.submitted.length === 0 && activeDoctors.length > 0 && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-300 rounded-lg flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-amber-800">
                <strong>No doctor has submitted preferences for {monthName} {year}.</strong>{" "}
                All doctors will be treated as fully available. Consider collecting preferences first.
              </p>
              <div className="mt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate(`/admin/preferences?year=${year}&month=${month}`)}
                >
                  Go to Preferences
                </Button>
              </div>
            </div>
          </div>
        )}

        {!isLoading && prefSummary && prefSummary.submitted.length > 0 && prefSummary.missing.length > 0 && (
          <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-start gap-3">
            <Info className="h-5 w-5 text-blue-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-blue-800">
                <strong>{prefSummary.missing.length}</strong> of{" "}
                {prefSummary.submitted.length + prefSummary.missing.length} doctors
                haven't submitted preferences yet and will be treated as fully available.
              </p>
              <div className="mt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate(`/admin/preferences?year=${year}&month=${month}`)}
                >
                  View Preferences
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Warning Info Boxes */}
        {!isLoading && hasAlertDays && !hasCriticalDays && (
          <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg flex items-start gap-3">
            <Info className="h-5 w-5 text-yellow-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-yellow-800">
                <strong>Coverage looks risky for some days.</strong> Before
                generating, you can update the active doctor list or edit
                doctors' monthly preferences.
              </p>
              <div className="mt-2 flex gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate("/admin/doctors")}
                >
                  Edit Active Doctors
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    navigate(`/admin/preferences?year=${year}&month=${month}`)
                  }
                >
                  Edit Monthly Preferences
                </Button>
              </div>
            </div>
          </div>
        )}

        {!isLoading && hasCriticalDays && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-red-800">
                <strong>
                  Some days are impossible to cover with the current inputs.
                </strong>{" "}
                Before generating, update the active doctor list or edit
                doctors' monthly preferences. If you still want to generate, you
                can generate with ignored days/slots.
              </p>
              <div className="mt-2 flex gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate("/admin/doctors")}
                >
                  Edit Active Doctors
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    navigate(`/admin/preferences?year=${year}&month=${month}`)
                  }
                >
                  Edit Monthly Preferences
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Solver error panel (structured 409 response) */}
        {solverError && (
          <SolverErrorPanel
            error={solverError}
            onRetryWithIgnore={handleRetryWithIgnore}
            onRetryWithHeadResolution={handleRetryWithHeadResolution}
            onDismiss={() => setSolverError(null)}
            generating={generating}
            doctors={activeDoctors}
          />
        )}

        {/* Plain error display */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800">
            {error}
          </div>
        )}

        {/* Availability Heatmap */}
        <AvailabilityHeatmap
          year={year}
          month={month}
          days={overview?.days || []}
          onDayClick={setDrilldownDay}
          loading={loadingOverview}
          solverErrorDays={solverErrorDays}
        />

        {/* Generate Button */}
        <div className="flex justify-center">
          <Button
            size="lg"
            onClick={handleGenerateClick}
            disabled={isLoading || generating || activeDoctors.length === 0}
            className="px-8"
          >
            <Sparkles className="h-5 w-5 mr-2" />
            {generating ? "Generating..." : "Generate Schedule"}
          </Button>
        </div>

        {activeDoctors.length === 0 && !loadingDoctors && (
          <p className="text-center text-muted-foreground mt-2">
            Please add active doctors before generating a schedule.
          </p>
        )}
      </main>

      {/* Day Drilldown Modal */}
      {drilldownDay !== null && (
        <DayDrilldownModal
          year={year}
          month={month}
          day={drilldownDay}
          onClose={() => setDrilldownDay(null)}
          solverIssues={getSolverIssuesForDay(drilldownDay)}
          doctors={activeDoctors}
        />
      )}

      {/* Ignore Gaps Modal (availability-based, before generating) */}
      {showIgnoreModal && (
        <IgnoreGapsModal
          year={year}
          month={month}
          criticalDays={criticalDays}
          onCancel={() => setShowIgnoreModal(false)}
          onAccept={handleAcceptIgnore}
          generating={generating}
        />
      )}
    </div>
  );
};
