import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";

export const DoctorLogin = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const user = await login({ email, password });

      // Doctors can login, admins can also access doctor panel
      if (user.role !== "doctor" && user.role !== "admin") {
        setError("Access denied. Invalid credentials.");
        setLoading(false);
        return;
      }

      // Redirect based on role
      if (user.role === "admin") {
        navigate("/admin");
      } else {
        navigate("/doctor");
      }
    } catch (err: any) {
      // Parse error message
      let errorMsg = "Invalid credentials. Please try again.";

      if (err.response?.data) {
        const data = err.response.data;
        if (typeof data === "string") {
          errorMsg = data;
        } else if (data.detail) {
          if (typeof data.detail === "string") {
            errorMsg = data.detail;
          } else if (data.detail.detail) {
            errorMsg = data.detail.detail;
          } else if (data.detail.code) {
            // Map error codes to user-friendly messages
            const errorMessages: { [key: string]: string } = {
              invalid_credentials: "Invalid email or password",
              inactive_user: "Your account is inactive. Contact administrator.",
              invalid_token: "Session expired. Please login again.",
            };
            errorMsg = errorMessages[data.detail.code] || data.detail.code;
          }
        }
      } else if (err.message) {
        errorMsg = err.message;
      }

      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-50 to-teal-100">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">
            Doctor Login
          </CardTitle>
          <CardDescription className="text-center">
            Enter your credentials to access your schedule
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="doctor@hospital.org"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            {error && (
              <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-md">
                {error}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in..." : "Sign In as Doctor"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
