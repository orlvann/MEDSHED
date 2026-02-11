import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { AdminHeader } from "../../components/shared/AdminHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  Users,
  Calendar,
  FileText,
  Settings,
  Clock,
  ClipboardCheck,
  CloudSun,
  ChevronRight,
  UserPlus,
} from "lucide-react";
import { doctorsApi } from "../../services/api";
import axios from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

interface WeatherData {
  temperature: number;
  condition: string;
  windSpeed: number;
}

const NavigationCard = ({
  title,
  description,
  icon: Icon,
  onClick,
  iconColor = "text-primary",
  badge,
}: {
  title: string;
  description: string;
  icon: any;
  onClick: () => void;
  iconColor?: string;
  badge?: number;
}) => (
  <Card
    className="cursor-pointer hover:shadow-lg transition-all duration-200 border-2 hover:border-primary group relative"
    onClick={onClick}
  >
    {badge !== undefined && badge > 0 && (
      <span className="absolute -top-2 -right-2 bg-red-600 text-white text-xs font-bold rounded-full h-6 w-6 flex items-center justify-center z-10">
        {badge}
      </span>
    )}
    <CardHeader className="p-4 sm:p-6">
      <div className="flex items-center space-x-3">
        <div
          className={`${iconColor} group-hover:scale-110 transition-transform duration-200`}
        >
          <Icon className="h-5 w-5 sm:h-6 sm:w-6" />
        </div>
        <CardTitle className="text-sm sm:text-lg">{title}</CardTitle>
      </div>
      <CardDescription className="mt-1.5 sm:mt-2 text-xs sm:text-sm">
        {description}
      </CardDescription>
    </CardHeader>
  </Card>
);

export const AdminHome = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [stats, setStats] = useState({
    totalEmployees: 0,
    activeEmployees: 0,
    schedulesSubmitted: 0,
    totalSchedules: 0,
  });
  const [pendingCount, setPendingCount] = useState(0);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [weatherLoading, setWeatherLoading] = useState(true);

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
        const response = await fetch(
          "https://api.open-meteo.com/v1/forecast?latitude=52.4064&longitude=16.9252&current=temperature_2m,weather_code,wind_speed_10m",
        );
        const data = await response.json();

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
          windSpeed: Math.round(data.current.wind_speed_10m),
        });
      } catch {
        setWeather(null);
      } finally {
        setWeatherLoading(false);
      }
    };

    loadWeather();
    const interval = setInterval(loadWeather, 15 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Load statistics
  useEffect(() => {
    const loadStats = async () => {
      try {
        const response = await doctorsApi.list({
          page: 1,
          size: 200,
          is_active: "all",
        });
        const activeCount = response.items.filter((d) => d.is_active).length;
        setStats({
          totalEmployees: response.total,
          activeEmployees: activeCount,
          schedulesSubmitted: 2,
          totalSchedules: 10,
        });
      } catch (err) {
        console.error("Failed to load stats:", err);
      }
    };
    loadStats();
  }, []);

  // Load pending doctors count and poll every 30 seconds
  useEffect(() => {
    const loadPendingCount = async () => {
      try {
        const token = localStorage.getItem("access_token");
        const response = await axios.get(
          `${API_BASE_URL}/api/v1/admin/pending-doctors/count`,
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        );
        setPendingCount(response.data.count);
      } catch (err) {
        console.error("Failed to load pending count:", err);
      }
    };

    loadPendingCount();
    const interval = setInterval(loadPendingCount, 30000);
    return () => clearInterval(interval);
  }, []);

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

  const getUserName = () => {
    if (user?.first_name) {
      return user.first_name;
    }
    return "Admin";
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminHeader />
      <main className="container mx-auto px-3 sm:px-4 py-4 sm:py-8">
        {/* Greeting */}
        <Card className="mb-4 sm:mb-6">
          <CardContent className="py-3 sm:py-4">
            <h2 className="text-xl sm:text-2xl font-bold mb-0.5">
              Hello, {getUserName()}!
            </h2>
            <p className="text-sm text-muted-foreground">
              How are you doing today?
            </p>
          </CardContent>
        </Card>

        {/* Pending Doctors Banner */}
        {pendingCount > 0 && (
          <div
            className="mb-4 rounded-xl bg-gradient-to-r from-red-500 to-rose-400 p-3.5 sm:p-4 cursor-pointer active:scale-[0.98] hover:shadow-md transition-all shadow-sm"
            onClick={() => navigate("/admin/doctors")}
          >
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 sm:h-10 sm:w-10 rounded-xl bg-white/20 flex items-center justify-center flex-shrink-0">
                <UserPlus className="h-4 w-4 sm:h-5 sm:w-5 text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-white">
                  {pendingCount} pending doctor
                  {pendingCount !== 1 ? "s" : ""}
                </p>
                <p className="text-[12px] text-white/80 mt-0.5">
                  Review and approve new registrations
                </p>
              </div>
              <ChevronRight className="h-5 w-5 text-white/50 flex-shrink-0" />
            </div>
          </div>
        )}

        {/* === MOBILE TILES (hidden on lg+) === */}
        <div className="space-y-3 lg:hidden mb-4">
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

          {/* Stats Row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-100/80 p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <div className="h-6 w-6 rounded-md bg-blue-500 flex items-center justify-center shadow-sm">
                  <Users className="h-3 w-3 text-white" />
                </div>
                <span className="text-[11px] font-semibold text-blue-600 uppercase tracking-wider">
                  Doctors
                </span>
              </div>
              <p className="text-xl font-bold text-slate-800 leading-none">
                {stats.totalEmployees}
              </p>
              <p className="text-[11px] text-slate-500 mt-1.5">
                {stats.activeEmployees} active
              </p>
            </div>

            <div className="rounded-xl bg-gradient-to-br from-emerald-50 to-green-50 border border-emerald-100/80 p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <div className="h-6 w-6 rounded-md bg-emerald-500 flex items-center justify-center shadow-sm">
                  <ClipboardCheck className="h-3 w-3 text-white" />
                </div>
                <span className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">
                  Prefs
                </span>
              </div>
              <p className="text-xl font-bold text-slate-800 leading-none">
                {stats.schedulesSubmitted}/{stats.totalSchedules}
              </p>
              <p className="text-[11px] text-slate-500 mt-1.5">submitted</p>
            </div>
          </div>
        </div>

        {/* === DESKTOP STAT CARDS (hidden below lg) === */}
        <div className="hidden lg:grid grid-cols-4 gap-6 mb-8">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-3xl font-bold">{stats.totalEmployees}</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Total Employees
                  </p>
                  <p className="text-xs text-green-600 mt-1">
                    {stats.activeEmployees} active
                  </p>
                </div>
                <Users className="h-12 w-12 text-blue-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-3xl font-bold">
                    {stats.totalEmployees - stats.activeEmployees}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">Absent</p>
                </div>
                <Users className="h-12 w-12 text-orange-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-3xl font-bold tabular-nums">
                    {formatTime(currentTime)}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    {formatDate(currentTime)}
                  </p>
                </div>
                <Clock className="h-12 w-12 text-gray-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-3xl font-bold">
                    {stats.schedulesSubmitted}/{stats.totalSchedules}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Schedule submitted
                  </p>
                </div>
                <ClipboardCheck className="h-12 w-12 text-green-600" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Administration Section */}
        <div className="mb-3 sm:mb-6">
          <h3 className="text-lg sm:text-2xl font-bold">Administration</h3>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-6">
          <NavigationCard
            title="Doctors"
            description="Add, edit, or remove doctors"
            icon={Users}
            onClick={() => navigate("/admin/doctors")}
            iconColor="text-blue-600"
            badge={pendingCount}
          />
          <NavigationCard
            title="Admin Users"
            description="Manage admin accounts"
            icon={Users}
            onClick={() => navigate("/admin/users")}
            iconColor="text-purple-600"
          />
          <NavigationCard
            title="Preferences"
            description="Review doctor preferences"
            icon={Settings}
            onClick={() => navigate("/admin/preferences")}
            iconColor="text-indigo-600"
          />
          <NavigationCard
            title="Generate"
            description="Create new schedules"
            icon={Calendar}
            onClick={() => navigate("/admin/generate")}
            iconColor="text-green-600"
          />
          <NavigationCard
            title="Schedules"
            description="Browse existing schedules"
            icon={FileText}
            onClick={() => navigate("/admin/schedules")}
            iconColor="text-orange-600"
          />
        </div>
      </main>
    </div>
  );
};
