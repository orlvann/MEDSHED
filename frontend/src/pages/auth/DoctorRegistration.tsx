import { useState } from "react";
import { useNavigate } from "react-router-dom";
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
import { CheckCircle } from "lucide-react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const DoctorRegistration = () => {
  const navigate = useNavigate();

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await axios.post(`${API_BASE_URL}/api/v1/doctors/register`, {
        first_name: firstName,
        last_name: lastName,
        email: email,
      });

      setSuccess(true);
    } catch (err: any) {
      let errorMsg = "Failed to submit registration. Please try again.";

      if (err.response?.data) {
        const data = err.response.data;
        if (typeof data === "string") {
          errorMsg = data;
        } else if (data.detail) {
          if (typeof data.detail === "string") {
            errorMsg = data.detail;
          } else if (data.detail.detail) {
            errorMsg = data.detail.detail;
          }
        }
      }

      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-50 to-teal-100">
        <Card className="w-full max-w-md mx-4 sm:mx-auto">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4">
              <CheckCircle className="h-16 w-16 text-green-600" />
            </div>
            <CardTitle className="text-2xl font-bold text-green-600">
              Registration Submitted!
            </CardTitle>
            <CardDescription className="text-base mt-2">
              Your registration request has been sent to the administrators.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-4 bg-green-50 border border-green-200 rounded-md">
              <p className="text-sm text-green-800">
                An administrator will review your request and send you an email
                with further instructions once approved.
              </p>
            </div>

            <div className="flex gap-2">
              <Button onClick={() => navigate("/login")} className="flex-1">
                Go to Login
              </Button>
              <Button
                onClick={() => {
                  setSuccess(false);
                  setFirstName("");
                  setLastName("");
                  setEmail("");
                }}
                variant="outline"
                className="flex-1"
              >
                Submit Another
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-50 to-teal-100">
      <Card className="w-full max-w-md mx-4 sm:mx-auto">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">
            Doctor Registration
          </CardTitle>
          <CardDescription className="text-center">
            Submit your information to register as a doctor
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="first_name">First Name *</Label>
              <Input
                id="first_name"
                type="text"
                placeholder="Enter your first name"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="last_name">Last Name *</Label>
              <Input
                id="last_name"
                type="text"
                placeholder="Enter your last name"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email *</Label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            {error && (
              <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-md">
                {error}
              </div>
            )}
            <div className="text-xs text-muted-foreground space-y-1 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p>• Your registration will be reviewed by an administrator</p>
              <p>
                • You will receive an email once your registration is approved
              </p>
              <p>• Make sure to use a valid email address</p>
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Submitting..." : "Submit Registration"}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => navigate("/login")}
              disabled={loading}
            >
              Back to Login
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
