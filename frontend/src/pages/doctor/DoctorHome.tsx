import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Header } from "../../components/shared/Header";
import { Card, CardContent } from "../../components/ui/card";
import { ScheduleCalendar } from "../../components/doctor/ScheduleCalendar";
import { Calendar, CheckCircle, AlertCircle } from "lucide-react";
import {
  preferencesApi,
  doctorPreferencesApi,
  schedulesApi,
  doctorsApi,
} from "../../services/api";
import type {
  PreferencesDeadlineRead,
  PreferenceWorkingRead,
  SchedulePublishedRead,
  Assignment,
  Doctor,
} from "../../types";

// Get time remaining until deadline
const getTimeRemaining = (deadline: string | null): { days: number; isPast: boolean } | null => {
  if (!deadline) return null;
  const now = new Date();
  const deadlineDate = new Date(deadline);
  const total = deadlineDate.getTime() - now.getTime();

  if (total <= 0) {
    return { days: 0, isPast: true };
  }

  const days = Math.ceil(total / (1000 * 60 * 60 * 24));
  return { days, isPast: false };
};

export const DoctorHome = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  // Current period
  const now = new Date();
  const [myScheduleYear, setMyScheduleYear] = useState(now.getFullYear());
  const [myScheduleMonth, setMyScheduleMonth] = useState(now.getMonth() + 1);
  const [teamScheduleYear, setTeamScheduleYear] = useState(now.getFullYear());
  const [teamScheduleMonth, setTeamScheduleMonth] = useState(now.getMonth() + 1);

  // Data states
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(null);
  const [preferences, setPreferences] = useState<PreferenceWorkingRead | null>(null);
  const [publishedSchedule, setPublishedSchedule] = useState<SchedulePublishedRead | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);

  // Selected dates for calendars
  const [mySelectedDate, setMySelectedDate] = useState<number | null>(now.getDate());
  const [teamSelectedDate, setTeamSelectedDate] = useState<number | null>(now.getDate());

  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        // Load deadline for current month
        const deadlineData = await preferencesApi.getDeadline(
          now.getFullYear(),
          now.getMonth() + 1
        );
        setDeadline(deadlineData);

        // Load my preferences to get status and doctor_id
        const prefsData = await doctorPreferencesApi.getMyPreferences(
          now.getFullYear(),
          now.getMonth() + 1
        );
        setPreferences(prefsData);

        // Load doctors list for name mapping
        const doctorsList = await doctorsApi.list({ page: 1, size: 200, is_active: "all" });
        setDoctors(doctorsList.items);
      } catch (err) {
        console.error("Failed to load initial data:", err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []);

  // Load published schedule when month changes
  useEffect(() => {
    const loadSchedule = async () => {
      try {
        const schedule = await schedulesApi.getPublished(teamScheduleYear, teamScheduleMonth);
        setPublishedSchedule(schedule);
      } catch (err) {
        // 404 means no published schedule yet
        setPublishedSchedule(null);
      }
    };

    loadSchedule();
  }, [teamScheduleYear, teamScheduleMonth]);

  // Get user's display name for greeting
  const getUserName = () => {
    if (user?.first_name) {
      return user.first_name;
    }
    return "Doctor";
  };

  // Get deadline info
  const deadlineInfo = deadline ? getTimeRemaining(deadline.deadline) : null;

  // Create doctor names map
  const doctorNamesMap = new Map<number, string>();
  doctors.forEach((d) => {
    doctorNamesMap.set(d.id, `${d.first_name} ${d.last_name}`);
  });

  // Get my assignments (filter from published schedule)
  const getMyAssignments = (): Assignment[] => {
    if (!publishedSchedule?.published?.payload?.assignments || !preferences) {
      return [];
    }
    return publishedSchedule.published.payload.assignments.filter(
      (a) => a.doctor_id === preferences.doctor_id
    );
  };

  // Get all team assignments
  const getTeamAssignments = (): Assignment[] => {
    if (!publishedSchedule?.published?.payload?.assignments) {
      return [];
    }
    return publishedSchedule.published.payload.assignments;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="container mx-auto px-4 py-6">
          <div className="animate-pulse">
            <div className="h-8 bg-gray-200 rounded w-1/4 mb-4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/3 mb-8"></div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="h-48 bg-gray-200 rounded"></div>
              <div className="lg:col-span-2 h-48 bg-gray-200 rounded"></div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-4 py-6">
        {/* Greeting */}
        <Card className="mb-6">
          <CardContent className="py-4">
            <h2 className="text-xl font-bold mb-0.5">Hello, {getUserName()}!</h2>
            <p className="text-sm text-muted-foreground">How are you doing today?</p>
          </CardContent>
        </Card>

        {/* Main content grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left column - Info cards */}
          <div className="space-y-3">
            {/* Deadline Card */}
            <Card className="min-h-[100px]">
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-2">Deadline</h3>
                {deadlineInfo ? (
                  <>
                    <p className="text-sm text-gray-700 mb-1">
                      Deadline: {deadlineInfo.days} days
                    </p>
                    {!deadlineInfo.isPast ? (
                      <div className="flex items-center gap-1.5 text-green-600">
                        <CheckCircle className="h-3.5 w-3.5" />
                        <span className="text-xs">you still have time!</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-red-600">
                        <AlertCircle className="h-3.5 w-3.5" />
                        <span className="text-xs">deadline has passed</span>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-gray-500">No deadline set</p>
                )}
              </CardContent>
            </Card>

            {/* Status Card */}
            <Card className="min-h-[100px]">
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-2">Status</h3>
                {preferences?.status === "submitted" ? (
                  <>
                    <p className="text-sm text-gray-700 mb-1">
                      your preferences are submitted
                    </p>
                    <div className="flex items-center gap-1.5 text-green-600">
                      <CheckCircle className="h-3.5 w-3.5" />
                      <span className="text-xs">all done!</span>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-gray-700 mb-1">
                      your preferences are not submitted
                    </p>
                    <div className="flex items-center gap-1.5 text-red-600">
                      <AlertCircle className="h-3.5 w-3.5" />
                      <span className="text-xs">prepare your schedule!</span>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Preferences Card */}
            <Card
              className="min-h-[100px] cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => navigate("/doctor/preferences")}
            >
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-semibold mb-0.5">Preferences</h3>
                    <p className="text-xs text-muted-foreground">
                      set your preferences
                    </p>
                  </div>
                  <Calendar className="h-6 w-6 text-gray-300" />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right column - Calendars */}
          <div className="lg:col-span-2 space-y-4">
            {/* My Schedule Calendar */}
            <ScheduleCalendar
              year={myScheduleYear}
              month={myScheduleMonth}
              onMonthChange={(y, m) => {
                setMyScheduleYear(y);
                setMyScheduleMonth(m);
                // Reload schedule for new month
                setTeamScheduleYear(y);
                setTeamScheduleMonth(m);
              }}
              assignments={getMyAssignments()}
              selectedDate={mySelectedDate}
              onDateSelect={setMySelectedDate}
              title="My schedule"
              onViewAll={() => navigate("/doctor/schedules")}
              doctorNames={doctorNamesMap}
            />

            {/* Team Schedule Calendar */}
            <ScheduleCalendar
              year={teamScheduleYear}
              month={teamScheduleMonth}
              onMonthChange={(y, m) => {
                setTeamScheduleYear(y);
                setTeamScheduleMonth(m);
              }}
              assignments={getTeamAssignments()}
              selectedDate={teamSelectedDate}
              onDateSelect={setTeamSelectedDate}
              title="Team schedule"
              onViewAll={() => navigate("/doctor/schedules")}
              doctorNames={doctorNamesMap}
            />
          </div>
        </div>
      </main>
    </div>
  );
};
