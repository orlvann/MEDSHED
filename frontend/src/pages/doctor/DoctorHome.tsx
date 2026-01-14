import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Header } from "../../components/shared/Header";
import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { ScheduleCalendar } from "../../components/doctor/ScheduleCalendar";
import {
  Calendar,
  CheckCircle,
  AlertCircle,
  Clock,
  ClipboardList,
  CloudSun,
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
  Doctor,
} from "../../types";

// Get time remaining until deadline
const getTimeRemaining = (
  deadline: string | null
): { days: number; isPast: boolean } | null => {
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
  const [doctors, setDoctors] = useState<Doctor[]>([]);
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

        // Load doctors list for name mapping
        const doctorsList = await doctorsApi.list({
          page: 1,
          size: 200,
          is_active: "all",
        });
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
          <Card className="mb-6 border-orange-300 bg-orange-50">
            <CardContent className="py-4 flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-orange-600 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium text-orange-800">
                  Deadline approaching! Only {deadlineInfo?.days} day
                  {deadlineInfo?.days !== 1 ? "s" : ""} left.
                </p>
                <p className="text-xs text-orange-600">
                  Please submit your preferences before the deadline.
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="border-orange-300 text-orange-700 hover:bg-orange-100"
                onClick={() => navigate("/doctor/preferences")}
              >
                Fill Now
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Main content grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left column - Info cards */}
          <div className="space-y-3">
            {/* Current Time Card */}
            <Card className="min-h-[100px]">
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-1 flex items-center gap-2">
                  <Clock className="h-4 w-4 text-blue-600" />
                  Current Time
                </h3>
                <p className="text-2xl font-bold text-blue-600">
                  {formatTime(currentTime)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {formatDate(currentTime)}
                </p>
              </CardContent>
            </Card>

            {/* Weather Card */}
            <Card className="min-h-[100px]">
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-1 flex items-center gap-2">
                  <CloudSun className="h-4 w-4 text-orange-500" />
                  Weather in Poznan
                </h3>
                {weatherLoading ? (
                  <p className="text-sm text-gray-500">Loading...</p>
                ) : weather ? (
                  <>
                    <p className="text-2xl font-bold text-orange-600">
                      {weather.temperature}°C
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {weather.condition}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Humidity: {weather.humidity}% | Wind: {weather.windSpeed}{" "}
                      km/h
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-gray-500">
                    Unable to load weather
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Deadline Card */}
            <Card className="min-h-[100px]">
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-purple-600" />
                  Deadline
                </h3>
                {deadlineInfo ? (
                  <>
                    <p className="text-sm text-gray-700 mb-1">
                      {deadlineInfo.days} day
                      {deadlineInfo.days !== 1 ? "s" : ""} remaining
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
                <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
                  <ClipboardList className="h-4 w-4 text-indigo-600" />
                  Status
                </h3>
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
              className="min-h-[100px] cursor-pointer hover:shadow-md transition-shadow border-2 hover:border-primary"
              onClick={() => navigate("/doctor/preferences")}
            >
              <CardContent className="py-4">
                <h3 className="text-base font-semibold mb-0.5 flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-green-600" />
                  Preferences
                </h3>
                <p className="text-xs text-muted-foreground">
                  set your preferences
                </p>
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
