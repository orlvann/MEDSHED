import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  ActiveDoctorsList,
  AvailabilityHeatmap,
  DayDrilldownModal,
  IgnoreGapsModal,
} from "../../components/admin/generate";
import { doctorsApi, availabilityApi, schedulesApi } from "../../services/api";
import type {
  Doctor,
  AvailabilityOverviewRead,
  AvailabilityDayOverview,
  IgnoredSlot,
} from "../../types";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Info,
  Sparkles,
} from "lucide-react";

export const GenerateSchedule = () => {
  const navigate = useNavigate();

  // Period selection
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  // Data
  const [activeDoctors, setActiveDoctors] = useState<Doctor[]>([]);
  const [overview, setOverview] = useState<AvailabilityOverviewRead | null>(
    null,
  );

  // Loading states
  const [loadingDoctors, setLoadingDoctors] = useState(true);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Error states
  const [error, setError] = useState<string | null>(null);

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

  // Fetch availability overview
  const fetchOverview = useCallback(async () => {
    try {
      setLoadingOverview(true);
      setError(null);
      const data = await availabilityApi.getOverview(year, month);
      setOverview(data);
    } catch (err: any) {
      console.error("Failed to load availability:", err);
      setError(
        err.response?.data?.detail || "Failed to load availability data",
      );
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

  // Handle generate button click
  const handleGenerateClick = () => {
    if (hasCriticalDays) {
      setShowIgnoreModal(true);
    } else {
      handleGenerate([]);
    }
  };

  // Generate schedule
  const handleGenerate = async (ignoreSlots: IgnoredSlot[]) => {
    try {
      setGenerating(true);
      setError(null);

      await schedulesApi.generate({
        year,
        month,
        participant_doctor_ids: activeDoctors.map((d) => d.id),
        ignore_days: [],
        ignore_slots: ignoreSlots,
      });

      // Navigate to schedules page on success
      navigate(`/admin/schedules?year=${year}&month=${month}`);
    } catch (err: any) {
      console.error("Failed to generate schedule:", err);
      setError(err.response?.data?.detail || "Failed to generate schedule");
      setShowIgnoreModal(false);
    } finally {
      setGenerating(false);
    }
  };

  // Handle accept from ignore modal
  const handleAcceptIgnore = (ignoreSlots: IgnoredSlot[]) => {
    handleGenerate(ignoreSlots);
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

        {/* Error display */}
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
        />
      )}

      {/* Ignore Gaps Modal */}
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
