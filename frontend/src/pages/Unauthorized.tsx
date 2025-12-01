import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { ShieldAlert, ArrowLeft } from "lucide-react";

export const Unauthorized = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleGoBack = () => {
    if (user?.role === "doctor" || user?.role === "doctor_admin") {
      navigate("/doctor");
    } else if (user?.role === "admin") {
      navigate("/admin");
    } else {
      navigate("/login");
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-red-50 to-orange-100">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4">
            <ShieldAlert className="h-16 w-16 text-red-600" />
          </div>
          <CardTitle className="text-2xl font-bold">Access Denied</CardTitle>
          <CardDescription className="text-base mt-2">
            You don't have permission to access this page.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-800">
              <strong>Current Role:</strong> {user?.role || "Unknown"}
            </p>
            <p className="text-sm text-red-800 mt-1">
              <strong>Email:</strong> {user?.email || "Unknown"}
            </p>
          </div>

          <p className="text-sm text-center text-muted-foreground">
            This area is restricted. If you believe this is an error, please
            contact your administrator.
          </p>

          <div className="flex flex-col space-y-2">
            <Button onClick={handleGoBack} className="w-full">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Go to My Dashboard
            </Button>
            <Button onClick={handleLogout} variant="outline" className="w-full">
              Logout
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
