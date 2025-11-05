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
    return <Navigate to="/login/admin" replace />;
  }

  if (requiredRole && user.role !== requiredRole) {
    // User doesn't have required role
    return <Navigate to="/unauthorized" replace />;
  }

  return <>{children}</>;
};
