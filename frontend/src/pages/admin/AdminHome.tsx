import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Header } from "../../components/shared/Header";
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
} from "lucide-react";
import { doctorsApi } from "../../services/api";
import axios from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const StatCard = ({
  icon: Icon,
  value,
  label,
  sublabel,
  iconColor = "text-blue-600",
}: {
  icon: any;
  value: string | number;
  label: string;
  sublabel?: string;
  iconColor?: string;
}) => (
  <Card>
    <CardContent className="pt-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-3xl font-bold">{value}</p>
          <p className="text-sm text-muted-foreground mt-1">{label}</p>
          {sublabel && (
            <p className="text-xs text-green-600 mt-1">{sublabel}</p>
          )}
        </div>
        <div className={`${iconColor}`}>
          <Icon className="h-12 w-12" />
        </div>
      </div>
    </CardContent>
  </Card>
);

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
    <CardHeader>
      <div className="flex items-center space-x-3">
        <div
          className={`${iconColor} group-hover:scale-110 transition-transform duration-200`}
        >
          <Icon className="h-6 w-6" />
        </div>
        <CardTitle className="text-lg">{title}</CardTitle>
      </div>
      <CardDescription className="mt-2">{description}</CardDescription>
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

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
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
          schedulesSubmitted: 2, // Mock data for now
          totalSchedules: 10, // Mock data for now
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
          }
        );
        setPendingCount(response.data.count);
      } catch (err) {
        console.error("Failed to load pending count:", err);
      }
    };

    loadPendingCount();
    const interval = setInterval(loadPendingCount, 30000); // Poll every 30 seconds

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
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  };

  // Get user's display name for greeting
  const getUserName = () => {
    if (user?.first_name) {
      return user.first_name;
    }
    return "Admin";
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-4 py-8">
        {/* Greeting */}
        <div className="mb-8">
          <h2 className="text-3xl font-bold mb-2">Hello, {getUserName()}!</h2>
          <p className="text-muted-foreground">How are you doing today?</p>
        </div>

        {/* Statistics Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard
            icon={Users}
            value={stats.totalEmployees}
            label="Total Employees"
            sublabel={
              stats.totalEmployees > 0
                ? `${
                    stats.totalEmployees - stats.activeEmployees
                  } new employees added!`
                : undefined
            }
            iconColor="text-blue-600"
          />
          <StatCard
            icon={Users}
            value={stats.totalEmployees - stats.activeEmployees}
            label="Absent"
            sublabel={
              stats.totalEmployees > 0
                ? `+1% Increase than yesterday`
                : undefined
            }
            iconColor="text-orange-600"
          />
          <StatCard
            icon={Clock}
            value={formatTime(currentTime)}
            label={`Today:\n${formatDate(currentTime)}`}
            iconColor="text-gray-600"
          />
          <StatCard
            icon={ClipboardCheck}
            value={`${stats.schedulesSubmitted}/${stats.totalSchedules}`}
            label="Schedule submitted"
            sublabel={`${stats.schedulesSubmitted} more employees submitted!`}
            iconColor="text-green-600"
          />
        </div>

        {/* MedSched Administration */}
        <div className="mb-6">
          <h3 className="text-2xl font-bold mb-6">MedSched Administration</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <NavigationCard
            title="Manage Doctors"
            description="Add, edit, or remove doctors from the system"
            icon={Users}
            onClick={() => navigate("/admin/doctors")}
            iconColor="text-blue-600"
            badge={pendingCount}
          />
          <NavigationCard
            title="Manage Admin Users"
            description="Manage users with admin role"
            icon={Users}
            onClick={() => navigate("/admin/users")}
            iconColor="text-purple-600"
          />
          <NavigationCard
            title="Manage Preferences"
            description="Review and manage doctor preferences"
            icon={Settings}
            onClick={() => navigate("/admin/preferences")}
            iconColor="text-indigo-600"
          />
          <NavigationCard
            title="Generate Schedules"
            description="Create new schedules with the solver"
            icon={Calendar}
            onClick={() => navigate("/admin/generate")}
            iconColor="text-green-600"
          />
          <NavigationCard
            title="View Schedules"
            description="Browse and manage existing schedules"
            icon={FileText}
            onClick={() => navigate("/admin/schedules")}
            iconColor="text-orange-600"
          />
        </div>
      </main>
    </div>
  );
};
