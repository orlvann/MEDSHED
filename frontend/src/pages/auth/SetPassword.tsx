import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
import axios from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const SetPassword = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const token = searchParams.get("token");

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [isExpired, setIsExpired] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // Validation
    if (!token) {
      setError("Invalid or missing token");
      return;
    }

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters long");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);

    try {
      await axios.post(`${API_BASE_URL}/api/v1/auth/set-password`, {
        token,
        new_password: newPassword,
      });

      setSuccess(true);

      // Redirect to login after 2 seconds
      setTimeout(() => {
        navigate("/login", {
          state: { message: "Password set successfully! You can now log in." },
        });
      }, 2000);
    } catch (err: any) {
      let errorMsg = "Failed to set password. Please try again.";
      let tokenExpired = false;

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
            const errorCode = data.detail.code;
            if (
              errorCode === "invalid_token" ||
              errorCode === "expired_token"
            ) {
              tokenExpired = true;
              errorMsg = "This link has expired";
            } else {
              const errorMessages: { [key: string]: string } = {
                invalid_token: "Invalid or expired password reset token",
                expired_token: "Password reset token has expired",
              };
              errorMsg = errorMessages[errorCode] || errorCode;
            }
          }
        }
      }

      setError(errorMsg);
      setIsExpired(tokenExpired);
    } finally {
      setLoading(false);
    }
  };

  const getPasswordStrength = (password: string): string => {
    if (password.length === 0) return "";
    if (password.length < 8) return "Weak";
    if (password.length < 12) return "Medium";
    return "Strong";
  };

  const getPasswordStrengthColor = (strength: string): string => {
    switch (strength) {
      case "Weak":
        return "text-red-600";
      case "Medium":
        return "text-yellow-600";
      case "Strong":
        return "text-green-600";
      default:
        return "";
    }
  };

  if (!token) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-2xl font-bold text-center text-red-600">
              Invalid Link
            </CardTitle>
            <CardDescription className="text-center">
              The password reset link is invalid or missing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => navigate("/login")} className="w-full">
              Go to Login
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (success) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-2xl font-bold text-center text-green-600">
              Success!
            </CardTitle>
            <CardDescription className="text-center">
              Your password has been set successfully.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-center text-sm text-muted-foreground">
              Redirecting to login...
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const passwordStrength = getPasswordStrength(newPassword);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">
            Set Your Password
          </CardTitle>
          <CardDescription className="text-center">
            Create a strong password for your account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new_password">New Password</Label>
              <Input
                id="new_password"
                type="password"
                placeholder="Enter your new password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                disabled={loading}
                minLength={8}
              />
              {passwordStrength && (
                <p
                  className={`text-xs ${getPasswordStrengthColor(
                    passwordStrength
                  )}`}
                >
                  Password strength: {passwordStrength}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm_password">Confirm Password</Label>
              <Input
                id="confirm_password"
                type="password"
                placeholder="Confirm your password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                disabled={loading}
                minLength={8}
              />
            </div>
            {error && (
              <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-md">
                {error}
                {isExpired && (
                  <p className="mt-2 text-xs">
                    You can request a new password reset link.
                  </p>
                )}
              </div>
            )}
            {isExpired && (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => navigate("/forgot-password")}
                >
                  Reset Password
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => navigate("/login")}
                >
                  Back to Login
                </Button>
              </div>
            )}
            <div className="text-xs text-muted-foreground space-y-1">
              <p>• Password must be at least 8 characters</p>
              <p>• Use a mix of letters, numbers, and symbols for security</p>
            </div>
            {!isExpired && (
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Setting Password..." : "Set Password"}
              </Button>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
