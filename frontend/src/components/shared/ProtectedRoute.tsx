import { Navigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import type { Role } from "../../types";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: Role;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRole,
}) => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  if (!user) {
    // Not authenticated, redirect to login
    return <Navigate to="/login" replace />;
  }

  if (requiredRole) {
    // Allow doctor_admin to access both admin and doctor routes
    // Admin can only access admin routes, not doctor routes
    const hasAccess =
      (requiredRole === "admin" && (user.role === "admin" || user.role === "doctor_admin")) ||
      (requiredRole === "doctor" && (user.role === "doctor" || user.role === "doctor_admin"));

    if (!hasAccess) {
      return <Navigate to="/unauthorized" replace />;
    }
  }

  return <>{children}</>;
};
