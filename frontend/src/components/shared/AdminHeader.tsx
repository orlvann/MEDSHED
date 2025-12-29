import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../ui/button";
import { LogOut, Calendar, ArrowLeft } from "lucide-react";

export const AdminHeader = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleBackToDoctor = () => {
    navigate("/doctor");
  };

  // Check if user is a doctor_admin (has access to both doctor and admin panels)
  const isDoctorAdmin = user?.role === "doctor_admin";

  return (
    <header className="border-b bg-white shadow-sm">
      <div className="container mx-auto px-4 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Calendar className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold">MedShed</h1>
          <span className="ml-2 px-2 py-1 text-xs bg-primary/10 text-primary rounded">
            Admin
          </span>
        </div>
        <div className="flex items-center space-x-3">
          {isDoctorAdmin && (
            <Button
              onClick={handleBackToDoctor}
              variant="outline"
              size="sm"
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Doctor Panel
            </Button>
          )}
          <Button onClick={handleLogout} variant="outline" size="sm">
            <LogOut className="h-4 w-4 mr-2" />
            Logout
          </Button>
        </div>
      </div>
    </header>
  );
};
