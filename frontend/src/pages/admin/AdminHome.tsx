import { useNavigate } from "react-router-dom";
import { Header } from "../../components/shared/Header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Users, Calendar, FileText, Settings } from "lucide-react";

const NavigationCard = ({
  title,
  description,
  icon: Icon,
  onClick,
}: {
  title: string;
  description: string;
  icon: any;
  onClick: () => void;
}) => (
  <Card
    className="cursor-pointer hover:shadow-lg transition-shadow duration-200 border-2 hover:border-primary"
    onClick={onClick}
  >
    <CardHeader>
      <div className="flex items-center space-x-2">
        <Icon className="h-6 w-6 text-primary" />
        <CardTitle>{title}</CardTitle>
      </div>
      <CardDescription>{description}</CardDescription>
    </CardHeader>
  </Card>
);

export const AdminHome = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h2 className="text-3xl font-bold mb-2">Admin Dashboard</h2>
          <p className="text-muted-foreground">
            Welcome to MedShed. Select an action below to get started.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <NavigationCard
            title="Manage Doctors"
            description="Add, edit, or remove doctors from the system"
            icon={Users}
            onClick={() => navigate("/admin/doctors")}
          />
          <NavigationCard
            title="Manage Preferences"
            description="Review and manage doctor preferences"
            icon={Settings}
            onClick={() => navigate("/admin/preferences")}
          />
          <NavigationCard
            title="Generate Schedules"
            description="Create new schedules with the solver"
            icon={Calendar}
            onClick={() => navigate("/admin/generate")}
          />
          <NavigationCard
            title="View Schedules"
            description="Browse and manage existing schedules"
            icon={FileText}
            onClick={() => navigate("/admin/schedules")}
          />
        </div>
      </main>
    </div>
  );
};
