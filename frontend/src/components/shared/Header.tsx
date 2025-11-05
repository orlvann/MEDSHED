import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../ui/button";
import { LogOut, Calendar } from "lucide-react";

export const Header = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login/admin");
  };

  return (
    <header className="border-b bg-white shadow-sm">
      <div className="container mx-auto px-4 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Calendar className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold">MedShed</h1>
        </div>
        <div className="flex items-center space-x-4">
          <div className="text-sm">
            <span className="text-muted-foreground">Logged in as: </span>
            <span className="font-medium">{user?.email}</span>
            <span className="ml-2 px-2 py-1 text-xs bg-primary/10 text-primary rounded">
              {user?.role}
            </span>
          </div>
          <Button onClick={handleLogout} variant="outline" size="sm">
            <LogOut className="h-4 w-4 mr-2" />
            Logout
          </Button>
        </div>
      </div>
    </header>
  );
};
