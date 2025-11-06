import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { ProtectedRoute } from "./components/shared/ProtectedRoute";
import { AdminLogin } from "./pages/auth/AdminLogin";
import { DoctorLogin } from "./pages/auth/DoctorLogin";
import { AdminHome } from "./pages/admin/AdminHome";
import { DoctorsManagement } from "./pages/admin/DoctorsManagement";
import { Unauthorized } from "./pages/Unauthorized";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Redirect root to doctor login (admin login is hidden) */}
          <Route path="/" element={<Navigate to="/login/doctor" replace />} />

          {/* Auth routes */}
          <Route path="/login/admin" element={<AdminLogin />} />
          <Route path="/login/doctor" element={<DoctorLogin />} />

          {/* Unauthorized page */}
          <Route path="/unauthorized" element={<Unauthorized />} />

          {/* Admin routes - protected, admin only */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute requiredRole="admin">
                <AdminHome />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/doctors"
            element={
              <ProtectedRoute requiredRole="admin">
                <DoctorsManagement />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/preferences"
            element={
              <ProtectedRoute requiredRole="admin">
                <div className="flex items-center justify-center min-h-screen">
                  <div className="text-center">
                    <h1 className="text-2xl font-bold mb-4">
                      Preferences Management
                    </h1>
                    <p className="text-muted-foreground">Coming soon...</p>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/generate"
            element={
              <ProtectedRoute requiredRole="admin">
                <div className="flex items-center justify-center min-h-screen">
                  <div className="text-center">
                    <h1 className="text-2xl font-bold mb-4">
                      Generate Schedules
                    </h1>
                    <p className="text-muted-foreground">Coming soon...</p>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/schedules"
            element={
              <ProtectedRoute requiredRole="admin">
                <div className="flex items-center justify-center min-h-screen">
                  <div className="text-center">
                    <h1 className="text-2xl font-bold mb-4">View Schedules</h1>
                    <p className="text-muted-foreground">Coming soon...</p>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />

          {/* Doctor routes - protected, doctor only */}
          <Route
            path="/doctor"
            element={
              <ProtectedRoute requiredRole="doctor">
                <div className="flex items-center justify-center min-h-screen">
                  <div className="text-center">
                    <h1 className="text-2xl font-bold mb-4">
                      Doctor Dashboard
                    </h1>
                    <p className="text-muted-foreground">Coming soon...</p>
                  </div>
                </div>
              </ProtectedRoute>
            }
          />

          {/* 404 */}
          <Route
            path="*"
            element={
              <div className="flex items-center justify-center min-h-screen">
                <div className="text-center">
                  <h1 className="text-4xl font-bold mb-4">404</h1>
                  <p className="text-muted-foreground">Page not found</p>
                </div>
              </div>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
