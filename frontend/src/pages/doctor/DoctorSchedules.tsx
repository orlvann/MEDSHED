import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Header } from "../../components/shared/Header";
import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { FullScheduleCalendar } from "../../components/doctor/FullScheduleCalendar";
import { ExportPanel } from "../../components/doctor/ExportPanel";
import { Lock, ArrowLeft } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  doctorPreferencesApi,
  schedulesApi,
  doctorsApi,
} from "../../services/api";
import type {
  PreferenceWorkingRead,
  SchedulePublishedRead,
  Doctor,
} from "../../types";

type ScheduleViewMode = "my-schedule" | "team-schedule";

export const DoctorSchedules = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();

  // Current period defaults
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  // View mode state — initialise from ?view= query param
  const initialView = searchParams.get("view") === "team-schedule" ? "team-schedule" : "my-schedule";
  const [viewMode, setViewMode] = useState<ScheduleViewMode>(initialView);

  // Data states
  const [publishedSchedule, setPublishedSchedule] =
    useState<SchedulePublishedRead | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [preferences, setPreferences] = useState<PreferenceWorkingRead | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [scheduleLoading, setScheduleLoading] = useState(false);

  // Filter state for Team view
  const [highlightedDoctorId, setHighlightedDoctorId] = useState<number | null>(
    null
  );

  // Load initial data (doctors list and preferences)
  useEffect(() => {
    const loadInitialData = async () => {
      setLoading(true);
      try {
        // Load doctors list for name mapping
        const doctorsList = await doctorsApi.list({
          page: 1,
          size: 200,
          is_active: "all",
        });
        setDoctors(doctorsList.items);

        // Load my preferences to get doctor_id
        const prefsData = await doctorPreferencesApi.getMyPreferences(
          now.getFullYear(),
          now.getMonth() + 1
        );
        setPreferences(prefsData);
      } catch (err) {
        console.error("Failed to load initial data:", err);
      } finally {
        setLoading(false);
      }
    };

    loadInitialData();
  }, []);

  // Load published schedule when month changes
  useEffect(() => {
    const loadSchedule = async () => {
      setScheduleLoading(true);
      try {
        const schedule = await schedulesApi.getPublished(year, month);
        setPublishedSchedule(schedule);
      } catch (err) {
        // 404 means no published schedule yet
        setPublishedSchedule(null);
      } finally {
        setScheduleLoading(false);
      }
    };

    loadSchedule();
  }, [year, month]);

  // Create doctor names map
  const doctorNamesMap = new Map<number, string>();
  doctors.forEach((d) => {
    doctorNamesMap.set(d.id, `${d.first_name} ${d.last_name}`);
  });

  // Get user's display name for greeting
  const getUserDisplayName = () => {
    if (user?.first_name) {
      return user.first_name;
    }
    return "Doctor";
  };

  // Handle month change
  const handleMonthChange = (newYear: number, newMonth: number) => {
    setYear(newYear);
    setMonth(newMonth);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="mx-auto px-3 sm:px-4 py-4 sm:py-6 max-w-4xl">
          <div className="animate-pulse">
            <div className="h-8 bg-gray-200 rounded w-1/4 mb-4"></div>
            <div className="h-96 bg-gray-200 rounded"></div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="mx-auto px-3 sm:px-4 py-4 sm:py-6 max-w-4xl">
        <Card>
          <CardContent className="p-3 sm:p-6">
            {/* Back Button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/doctor")}
              className="mb-3 sm:mb-4 -ml-2 text-gray-600 hover:text-gray-900 h-8"
            >
              <ArrowLeft className="h-4 w-4 mr-1.5" />
              Back
            </Button>

            {/* Header Row */}
            <div className="flex items-center justify-between mb-4 sm:mb-6">
              <div className="flex items-center gap-2 min-w-0">
                <h1 className="text-lg sm:text-2xl font-bold truncate">
                  {viewMode === "my-schedule"
                    ? `Hi, ${getUserDisplayName()}!`
                    : "Team Schedule"}
                </h1>
                <Lock className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-gray-400 flex-shrink-0" />
              </div>

              {/* View Mode Dropdown */}
              <Select
                value={viewMode}
                onValueChange={(value) =>
                  setViewMode(value as ScheduleViewMode)
                }
              >
                <SelectTrigger className="w-[120px] sm:w-[160px] h-8 sm:h-9 text-xs sm:text-sm flex-shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="my-schedule">My Schedule</SelectItem>
                  <SelectItem value="team-schedule">Team Schedule</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Calendar with controls */}
            <FullScheduleCalendar
              year={year}
              month={month}
              onMonthChange={handleMonthChange}
              assignments={
                publishedSchedule?.published?.payload?.assignments || []
              }
              viewMode={viewMode}
              currentDoctorId={preferences?.doctor_id || null}
              doctorNames={doctorNamesMap}
              highlightedDoctorId={highlightedDoctorId}
              onHighlightChange={setHighlightedDoctorId}
              doctors={doctors}
              loading={scheduleLoading}
              hasPublishedSchedule={publishedSchedule !== null}
            />

            {/* Export Panel */}
            <div className="mt-4 sm:mt-6 flex justify-end">
              <ExportPanel />
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
};
