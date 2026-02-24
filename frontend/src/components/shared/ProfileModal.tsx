import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { authApi } from "../../services/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { LogOut, Shield, Save, Lock, Eye, EyeOff, Smartphone } from "lucide-react";

interface ProfileModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const ProfileModal = ({ open, onOpenChange }: ProfileModalProps) => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  // Profile form state
  const [firstName, setFirstName] = useState(user?.first_name || "");
  const [lastName, setLastName] = useState(user?.last_name || "");
  const [phoneNumber, setPhoneNumber] = useState(user?.phone_number || "");
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSuccess, setProfileSuccess] = useState(false);

  // Password form state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState(false);

  // Password visibility state
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const handleSaveProfile = async () => {
    setProfileLoading(true);
    setProfileError(null);
    setProfileSuccess(false);

    try {
      await authApi.updateProfile({
        first_name: firstName,
        last_name: lastName,
        phone_number: phoneNumber,
      });
      setProfileSuccess(true);
      // Refresh user data
      window.location.reload();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      setProfileError(error.response?.data?.detail || "Failed to update profile");
    } finally {
      setProfileLoading(false);
    }
  };

  const handleChangePassword = async () => {
    setPasswordError(null);
    setPasswordSuccess(false);

    if (newPassword !== confirmPassword) {
      setPasswordError("Passwords do not match");
      return;
    }

    if (newPassword.length < 8) {
      setPasswordError("Password must be at least 8 characters");
      return;
    }

    setPasswordLoading(true);

    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      setPasswordError(error.response?.data?.detail || "Failed to change password");
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
    onOpenChange(false);
  };

  const handleGoToAdmin = () => {
    navigate("/admin");
    onOpenChange(false);
  };

  const canAccessAdmin = user?.role === "admin" || user?.role === "doctor_admin";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] p-0 gap-0">
        <DialogHeader className="sticky top-0 bg-background z-10 px-4 sm:px-6 pt-4 sm:pt-6 pb-3 border-b">
          <DialogTitle>Profile Settings</DialogTitle>
        </DialogHeader>

        <div className="space-y-6 p-4 sm:p-6 pt-4">
          {/* Profile Section */}
          <form autoComplete="off" onSubmit={(e) => { e.preventDefault(); handleSaveProfile(); }} className="space-y-4">
            <h3 className="text-sm font-medium text-gray-900">Personal Information</h3>
            {/* Hidden decoy fields to absorb browser autofill */}
            <input type="text" name="fakeuser" autoComplete="off" style={{ display: "none" }} tabIndex={-1} />
            <input type="email" name="fakeemail" autoComplete="off" style={{ display: "none" }} tabIndex={-1} />
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="profile-first">First Name</Label>
                <Input
                  id="profile-first"
                  autoComplete="off"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  placeholder="First name"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="profile-last">Last Name</Label>
                <Input
                  id="profile-last"
                  autoComplete="off"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  placeholder="Last name"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="profile-phone">Phone Number</Label>
              <div className="relative">
                <Smartphone className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="profile-phone"
                  type="tel"
                  autoComplete="off"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="+48 123 456 789"
                  className="pl-9"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                For SMS deadline reminders. International format, e.g. +48...
              </p>
            </div>
            {profileError && (
              <p className="text-sm text-red-600">{profileError}</p>
            )}
            {profileSuccess && (
              <p className="text-sm text-green-600">Profile updated successfully!</p>
            )}
            <div className="flex gap-2">
              <Button
                type="submit"
                disabled={profileLoading}
                className={canAccessAdmin ? "flex-1" : "w-full"}
              >
                <Save className="h-4 w-4 mr-2" />
                {profileLoading ? "Saving..." : "Save Profile"}
              </Button>
              {canAccessAdmin && (
                <Button
                  type="button"
                  variant="default"
                  onClick={handleGoToAdmin}
                  className="flex-1"
                >
                  <Shield className="h-4 w-4 mr-2" />
                  Admin Panel
                </Button>
              )}
            </div>
          </form>

          {/* Change Password Section */}
          <div className="space-y-4 pt-2 border-t">
            <h3 className="text-sm font-medium text-gray-900">Change Password</h3>
            <div className="grid gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="currentPassword">Current Password</Label>
                <div className="relative">
                  <Input
                    id="currentPassword"
                    name="current-password"
                    type={showCurrentPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    placeholder="Enter current password"
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  >
                    {showCurrentPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="newPassword">New Password</Label>
                <div className="relative">
                  <Input
                    id="newPassword"
                    name="new-password"
                    type={showNewPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Enter new password"
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  >
                    {showNewPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="confirmPassword">Confirm New Password</Label>
                <div className="relative">
                  <Input
                    id="confirmPassword"
                    name="new-password"
                    type={showConfirmPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
            </div>
            {passwordError && (
              <p className="text-sm text-red-600">{passwordError}</p>
            )}
            {passwordSuccess && (
              <p className="text-sm text-green-600">Password changed successfully!</p>
            )}
            <Button
              variant="outline"
              onClick={handleChangePassword}
              disabled={passwordLoading || !currentPassword || !newPassword || !confirmPassword}
              className="w-full"
            >
              <Lock className="h-4 w-4 mr-2" />
              {passwordLoading ? "Changing..." : "Change Password"}
            </Button>
          </div>

          {/* Logout */}
          <div className="pt-2 border-t">
            <Button
              variant="destructive"
              onClick={handleLogout}
              className="w-full"
            >
              <LogOut className="h-4 w-4 mr-2" />
              Logout
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
