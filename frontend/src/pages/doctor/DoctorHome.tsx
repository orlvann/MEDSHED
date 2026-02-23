import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Header } from "../../components/shared/Header";
import { Card, CardContent } from "../../components/ui/card";
import { ScheduleCalendar } from "../../components/doctor/ScheduleCalendar";
import {
  Calendar,
  CheckCircle,
  AlertCircle,
  Clock,
  ClipboardList,
  CloudSun,
  ChevronRight,
} from "lucide-react";
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
  DoctorMini,
} from "../../types";
import { getTimeRemaining } from "../../components/preferences/types";

interface WeatherData {
  temperature: number;
  condition: string;
  humidity: number;
  windSpeed: number;
}

// Get next month for preferences (preferences are always for NEXT month)
const getNextMonth = () => {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth() + 2; // +2 because getMonth() is 0-based and we need NEXT month

  if (month > 12) {
    month = 1;
    year += 1;
  }

  return { year, month };
};

export const DoctorHome = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  // Current period
  const now = new Date();
  const [myScheduleYear, setMyScheduleYear] = useState(now.getFullYear());
  const [myScheduleMonth, setMyScheduleMonth] = useState(now.getMonth() + 1);
  const [teamScheduleYear, setTeamScheduleYear] = useState(now.getFullYear());
  const [teamScheduleMonth, setTeamScheduleMonth] = useState(
    now.getMonth() + 1
  );

  // Data states
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(
    null
  );
  const [preferences, setPreferences] = useState<PreferenceWorkingRead | null>(
    null
  );
  const [publishedSchedule, setPublishedSchedule] =
    useState<SchedulePublishedRead | null>(null);
  const [doctors, setDoctors] = useState<DoctorMini[]>([]);
  const [loading, setLoading] = useState(true);

  // Weather and time states
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(true);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Selected dates for calendars
  const [mySelectedDate, setMySelectedDate] = useState<number | null>(
    now.getDate()
  );
  const [teamSelectedDate, setTeamSelectedDate] = useState<number | null>(
    now.getDate()
  );

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Load weather data for Poznan
  useEffect(() => {
    const loadWeather = async () => {
      setWeatherLoading(true);
      try {
        // Using Open-Meteo API (free, no API key required)
        // Poznan coordinates: 52.4064, 16.9252
        const response = await fetch(
          "https://api.open-meteo.com/v1/forecast?latitude=52.4064&longitude=16.9252&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        );
        const data = await response.json();

        // Weather code to condition mapping (WMO codes)
        const weatherCodeToCondition = (code: number): string => {
          if (code === 0) return "Clear sky";
          if (code === 1) return "Mainly clear";
          if (code === 2) return "Partly cloudy";
          if (code === 3) return "Overcast";
          if (code >= 45 && code <= 48) return "Fog";
          if (code >= 51 && code <= 55) return "Drizzle";
          if (code >= 61 && code <= 65) return "Rain";
          if (code >= 71 && code <= 77) return "Snow";
          if (code >= 80 && code <= 82) return "Rain showers";
          if (code >= 85 && code <= 86) return "Snow showers";
          if (code >= 95) return "Thunderstorm";
          return "Unknown";
        };

        setWeather({
          temperature: Math.round(data.current.temperature_2m),
          condition: weatherCodeToCondition(data.current.weather_code),
          humidity: data.current.relative_humidity_2m,
          windSpeed: Math.round(data.current.wind_speed_10m),
        });
      } catch (err) {
        console.error("Failed to load weather:", err);
        setWeather(null);
      } finally {
        setWeatherLoading(false);
      }
    };

    loadWeather();
    // Refresh weather every 15 minutes
    const interval = setInterval(loadWeather, 15 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        // Get next month - preferences are always for NEXT month
        const nextPeriod = getNextMonth();

        // Load deadline for next month
        const deadlineData = await preferencesApi.getDeadline(
          nextPeriod.year,
          nextPeriod.month
        );
        setDeadline(deadlineData);

        // Load my preferences for next month to get status and doctor_id
        const prefsData = await doctorPreferencesApi.getMyPreferences(
          nextPeriod.year,
          nextPeriod.month
        );
        setPreferences(prefsData);

        // Load doctors list for name mapping (lightweight endpoint for all doctors)
        const doctorNames = await doctorsApi.listNames();
        setDoctors(doctorNames);
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
        const schedule = await schedulesApi.getPublished(
          teamScheduleYear,
          teamScheduleMonth
        );
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

  // Show warning banner if preferences not submitted and deadline is <= 7 days away
  const shouldShowWarning =
    preferences?.status !== "submitted" &&
    deadlineInfo &&
    !deadlineInfo.isPast &&
    deadlineInfo.days <= 7;

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

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
  };

  const formatDate = (date: Date) => {
    return date.toLocaleDateString("en-US", {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main className="container mx-auto px-3 sm:px-4 py-4 sm:py-6">
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
      <main className="container mx-auto px-3 sm:px-4 py-4 sm:py-6">
        {/* Greeting */}
        <Card className="mb-6">
          <CardContent className="py-4">
            <h2 className="text-xl font-bold mb-0.5">
              Hello, {getUserName()}!
            </h2>
            <p className="text-sm text-muted-foreground">
              How are you doing today?
            </p>
          </CardContent>
        </Card>

        {/* Warning Banner */}
        {shouldShowWarning && (
          <>
            {/* Mobile warning banner */}
            <div
              className="mb-4 lg:hidden rounded-xl bg-gradient-to-r from-orange-500 to-amber-500 p-4 cursor-pointer active:scale-[0.98] transition-all shadow-sm"
              onClick={() => navigate("/doctor/preferences")}
            >
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-xl bg-white/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <AlertCircle className="h-5 w-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-white">
                    Only {deadlineInfo?.days} day
                    {deadlineInfo?.days !== 1 ? "s" : ""} left!
                  </p>
                  <p className="text-[12px] text-white/80 mt-0.5">
                    Submit your preferences before the deadline
                  </p>
                </div>
                <ChevronRight className="h-5 w-5 text-white/50 flex-shrink-0 mt-1" />
              </div>
            </div>

            {/* Desktop warning banner */}
            <div
              className="mb-6 hidden lg:block rounded-xl bg-gradient-to-r from-orange-500 to-amber-500 p-4 cursor-pointer hover:shadow-md active:scale-[0.98] transition-all shadow-sm"
              onClick={() => navigate("/doctor/preferences")}
            >
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-white/20 flex items-center justify-center flex-shrink-0">
                  <AlertCircle className="h-5 w-5 text-white" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-bold text-white">
                    Deadline approaching! Only {deadlineInfo?.days} day
                    {deadlineInfo?.days !== 1 ? "s" : ""} left.
                  </p>
                  <p className="text-xs text-white/80">
                    Please submit your preferences before the deadline.
                  </p>
                </div>
                <ChevronRight className="h-5 w-5 text-white/50 flex-shrink-0" />
              </div>
            </div>
          </>
        )}

        {/* Main content grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left column - Mobile: compact tiles, Desktop: original cards */}
          <div>
            {/* === MOBILE TILES (hidden on lg+) === */}
            <div className="space-y-3 lg:hidden">
              {/* Time & Weather Row */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-gradient-to-br from-sky-50 to-blue-50 border border-sky-100/80 p-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <div className="h-6 w-6 rounded-md bg-sky-500 flex items-center justify-center shadow-sm">
                      <Clock className="h-3 w-3 text-white" />
                    </div>
                    <span className="text-[11px] font-semibold text-sky-600 uppercase tracking-wider">
                      Time
                    </span>
                  </div>
                  <p className="text-base font-bold text-slate-800 tracking-tight leading-none tabular-nums">
                    {formatTime(currentTime)}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-1.5 leading-tight">
                    {formatDate(currentTime)}
                  </p>
                </div>

                <div className="rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-100/80 p-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <div className="h-6 w-6 rounded-md bg-amber-500 flex items-center justify-center shadow-sm">
                      <CloudSun className="h-3 w-3 text-white" />
                    </div>
                    <span className="text-[11px] font-semibold text-amber-600 uppercase tracking-wider">
                      Poznan
                    </span>
                  </div>
                  {weatherLoading ? (
                    <div className="h-5 w-14 bg-amber-100 animate-pulse rounded" />
                  ) : weather ? (
                    <>
                      <p className="text-lg font-bold text-slate-800 tracking-tight leading-none">
                        {weather.temperature}°C
                      </p>
                      <p className="text-[11px] text-slate-500 mt-1.5 truncate">
                        {weather.condition} · {weather.windSpeed} km/h
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-slate-400">Unavailable</p>
                  )}
                </div>
              </div>

              {/* Deadline & Status Row */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-gradient-to-br from-violet-50 to-purple-50 border border-violet-100/80 p-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <div className="h-6 w-6 rounded-md bg-violet-500 flex items-center justify-center shadow-sm">
                      <Calendar className="h-3 w-3 text-white" />
                    </div>
                    <span className="text-[11px] font-semibold text-violet-600 uppercase tracking-wider">
                      Deadline
                    </span>
                  </div>
                  {deadlineInfo ? (
                    <>
                      <p className="text-[15px] font-bold text-slate-800 tracking-tight leading-none">
                        {deadlineInfo.days}d {deadlineInfo.hours}h{" "}
                        {deadlineInfo.minutes}m
                      </p>
                      <div
                        className={`flex items-center gap-1 mt-1.5 ${
                          !deadlineInfo.isPast
                            ? "text-emerald-600"
                            : "text-red-500"
                        }`}
                      >
                        {!deadlineInfo.isPast ? (
                          <CheckCircle className="h-3 w-3 flex-shrink-0" />
                        ) : (
                          <AlertCircle className="h-3 w-3 flex-shrink-0" />
                        )}
                        <span className="text-[11px] font-medium">
                          {!deadlineInfo.isPast ? "time remaining" : "passed"}
                        </span>
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-slate-400">Not set</p>
                  )}
                </div>

                <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100/80 p-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <div className="h-6 w-6 rounded-md bg-indigo-500 flex items-center justify-center shadow-sm">
                      <ClipboardList className="h-3 w-3 text-white" />
                    </div>
                    <span className="text-[11px] font-semibold text-indigo-600 uppercase tracking-wider">
                      Status
                    </span>
                  </div>
                  {preferences?.status === "submitted" ? (
                    <>
                      <p className="text-[15px] font-bold text-slate-800 leading-tight">
                        Submitted
                      </p>
                      <div className="flex items-center gap-1 mt-1.5 text-emerald-600">
                        <CheckCircle className="h-3 w-3 flex-shrink-0" />
                        <span className="text-[11px] font-medium">
                          all done!
                        </span>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-[15px] font-bold text-slate-800 leading-tight">
                        Pending
                      </p>
                      <div className="flex items-center gap-1 mt-1.5 text-red-500">
                        <AlertCircle className="h-3 w-3 flex-shrink-0" />
                        <span className="text-[11px] font-medium">
                          action needed
                        </span>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Preferences CTA */}
              <div
                className="rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 p-3.5 cursor-pointer hover:shadow-md active:scale-[0.98] transition-all"
                onClick={() => navigate("/doctor/preferences")}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="h-8 w-8 rounded-lg bg-white/20 flex items-center justify-center">
                      <Calendar className="h-4 w-4 text-white" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">
                        Set Preferences
                      </p>
                      <p className="text-[11px] text-white/70">
                        for next month's schedule
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="h-5 w-5 text-white/50" />
                </div>
              </div>
            </div>

            {/* === DESKTOP CARDS (hidden below lg) === */}
            <div className="hidden lg:grid grid-cols-1 gap-3">
              <div className="rounded-xl bg-gradient-to-br from-sky-50 to-blue-50 border border-sky-100/80 p-4 min-h-[100px]">
                <div className="flex items-center gap-2 mb-1">
                  <div className="h-7 w-7 rounded-md bg-sky-500 flex items-center justify-center shadow-sm">
                    <Clock className="h-3.5 w-3.5 text-white" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800">
                    Current Time
                  </h3>
                </div>
                <p className="text-2xl font-bold text-slate-800 tabular-nums">
                  {formatTime(currentTime)}
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  {formatDate(currentTime)}
                </p>
              </div>

              <div className="rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-100/80 p-4 min-h-[100px]">
                <div className="flex items-center gap-2 mb-1">
                  <div className="h-7 w-7 rounded-md bg-amber-500 flex items-center justify-center shadow-sm">
                    <CloudSun className="h-3.5 w-3.5 text-white" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800">
                    Weather in Poznan
                  </h3>
                </div>
                {weatherLoading ? (
                  <p className="text-sm text-slate-400">Loading...</p>
                ) : weather ? (
                  <>
                    <p className="text-2xl font-bold text-slate-800">
                      {weather.temperature}°C
                    </p>
                    <p className="text-xs text-slate-500">
                      {weather.condition}
                    </p>
                    <p className="text-xs text-slate-500">
                      Humidity: {weather.humidity}% | Wind:{" "}
                      {weather.windSpeed} km/h
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-slate-400">
                    Unable to load weather
                  </p>
                )}
              </div>

              <div className="rounded-xl bg-gradient-to-br from-violet-50 to-purple-50 border border-violet-100/80 p-4 min-h-[100px]">
                <div className="flex items-center gap-2 mb-2">
                  <div className="h-7 w-7 rounded-md bg-violet-500 flex items-center justify-center shadow-sm">
                    <Calendar className="h-3.5 w-3.5 text-white" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800">
                    Deadline
                  </h3>
                </div>
                {deadlineInfo ? (
                  <>
                    <div className="flex items-center gap-2 text-slate-800 mb-1">
                      <span className="font-medium">
                        <span className="text-lg">{deadlineInfo.days}</span>{" "}
                        <span className="text-sm">days</span>{" "}
                        <span className="text-lg">{deadlineInfo.hours}</span>{" "}
                        <span className="text-sm">hours</span>{" "}
                        <span className="text-lg">
                          {deadlineInfo.minutes}
                        </span>{" "}
                        <span className="text-sm">minutes</span>
                      </span>
                    </div>
                    {!deadlineInfo.isPast ? (
                      <div className="flex items-center gap-1.5 text-emerald-600">
                        <CheckCircle className="h-4 w-4" />
                        <span className="text-sm">
                          you still have time!
                        </span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-red-500">
                        <AlertCircle className="h-4 w-4" />
                        <span className="text-sm">deadline has passed</span>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-base text-slate-400">No deadline set</p>
                )}
              </div>

              <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100/80 p-4 min-h-[100px]">
                <div className="flex items-center gap-2 mb-2">
                  <div className="h-7 w-7 rounded-md bg-indigo-500 flex items-center justify-center shadow-sm">
                    <ClipboardList className="h-3.5 w-3.5 text-white" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800">
                    Status
                  </h3>
                </div>
                {preferences?.status === "submitted" ? (
                  <>
                    <p className="text-base text-slate-700 mb-1">
                      your preferences are submitted
                    </p>
                    <div className="flex items-center gap-1.5 text-emerald-600">
                      <CheckCircle className="h-4 w-4" />
                      <span className="text-sm">all done!</span>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-base text-slate-700 mb-1">
                      your preferences are not submitted
                    </p>
                    <div className="flex items-center gap-1.5 text-red-500">
                      <AlertCircle className="h-4 w-4" />
                      <span className="text-sm">
                        prepare your schedule!
                      </span>
                    </div>
                  </>
                )}
              </div>

              <div
                className="rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 p-4 min-h-[100px] cursor-pointer hover:shadow-md active:scale-[0.98] transition-all"
                onClick={() => navigate("/doctor/preferences")}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="h-9 w-9 rounded-lg bg-white/20 flex items-center justify-center">
                      <Calendar className="h-5 w-5 text-white" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white">
                        Preferences
                      </h3>
                      <p className="text-sm text-white/70">
                        set your preferences
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="h-5 w-5 text-white/50" />
                </div>
              </div>
            </div>
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
              allAssignments={getTeamAssignments()}
              myDoctorId={preferences?.doctor_id}
              selectedDate={mySelectedDate}
              onDateSelect={setMySelectedDate}
              title="My schedule"
              onViewAll={() => navigate("/doctor/schedules")}
              doctorNames={doctorNamesMap}
              variant="personal"
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
              onViewAll={() => navigate("/doctor/schedules?view=team-schedule")}
              doctorNames={doctorNamesMap}
              variant="team"
            />
          </div>
        </div>
      </main>
    </div>
  );
};
