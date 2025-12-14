import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../../components/shared/Header";
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../../components/ui/alert-dialog";
import { preferencesApi, doctorsApi } from "../../services/api";
import type {
  Doctor,
  PreferencesSummaryRead,
  PreferencesDeadlineRead,
  PreferenceWorkingRead,
  PreferenceWorkingPut,
} from "../../types";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Calendar,
  Clock,
  CheckCircle,
  XCircle,
  Pencil,
  Eye,
  Undo2,
  Redo2,
  Save,
  X,
  AlertTriangle,
} from "lucide-react";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Helper to get days in month
const getDaysInMonth = (year: number, month: number): number => {
  return new Date(year, month, 0).getDate();
};

// Helper to get first day of month (0 = Sunday, 1 = Monday, etc.)
const getFirstDayOfMonth = (year: number, month: number): number => {
  const day = new Date(year, month - 1, 1).getDay();
  return day === 0 ? 6 : day - 1; // Convert to Monday = 0
};

// Helper to format date
const formatDate = (dateStr: string | null): string => {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

// Helper to calculate days remaining
const getDaysRemaining = (deadline: string | null): number | null => {
  if (!deadline) return null;
  const now = new Date();
  const deadlineDate = new Date(deadline);
  const diff = deadlineDate.getTime() - now.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
};

// Default empty preference form
const getDefaultPreferences = (): PreferenceWorkingPut => ({
  unavailable_onsite_days: [],
  unavailable_oncall_days: [],
  preferred_onsite_days: [],
  preferred_oncall_days: [],
  min_onsite_total: null,
  max_onsite_total: null,
  target_onsite_total: null,
  min_oncall_total: null,
  max_oncall_total: null,
  target_oncall_total: null,
  max_onsite_weekends: null,
  target_onsite_weekends: null,
  max_oncall_weekends: null,
  target_oncall_weekends: null,
  preferred_onsite_weekdays: [],
  preferred_oncall_weekdays: [],
  avoid_onsite_weekdays: [],
  avoid_oncall_weekdays: [],
  allow_weekend_consecutive_onsite_oncall: false,
  preferred_partners: [],
  comments: null,
});

export const PreferencesManagement = () => {
  const navigate = useNavigate();

  // Period state
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  // Data state
  const [summary, setSummary] = useState<PreferencesSummaryRead | null>(null);
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter state
  const [statusFilter, setStatusFilter] = useState<"all" | "submitted" | "missing">("all");

  // Deadline dialog state
  const [showDeadlineConfirm, setShowDeadlineConfirm] = useState(false);
  const [showDeadlinePicker, setShowDeadlinePicker] = useState(false);
  const [newDeadline, setNewDeadline] = useState("");
  const [deadlineLoading, setDeadlineLoading] = useState(false);

  // Edit modal state
  const [selectedDoctor, setSelectedDoctor] = useState<Doctor | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [preferenceData, setPreferenceData] = useState<PreferenceWorkingRead | null>(null);
  const [formData, setFormData] = useState<PreferenceWorkingPut>(getDefaultPreferences());
  const [formLoading, setFormLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);

  // Fetch all data for period
  const fetchData = async () => {
    try {
      setLoading(true);
      setError("");

      const [summaryRes, deadlineRes, doctorsRes] = await Promise.all([
        preferencesApi.getSummary(year, month),
        preferencesApi.getDeadline(year, month),
        doctorsApi.list({ size: 200, is_active: "true" }),
      ]);

      setSummary(summaryRes);
      setDeadline(deadlineRes);
      setDoctors(doctorsRes.items);
    } catch (err: any) {
      setError(err.response?.data?.detail?.detail || "Failed to load data");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [year, month]);

  // Filtered doctors with status
  const doctorsWithStatus = useMemo(() => {
    if (!summary) return [];

    return doctors.map((doctor) => ({
      ...doctor,
      preferenceStatus: summary.submitted.includes(doctor.id)
        ? ("submitted" as const)
        : ("missing" as const),
    }));
  }, [doctors, summary]);

  const filteredDoctors = useMemo(() => {
    if (statusFilter === "all") return doctorsWithStatus;
    return doctorsWithStatus.filter((d) => d.preferenceStatus === statusFilter);
  }, [doctorsWithStatus, statusFilter]);

  // Month navigation
  const goToPrevMonth = () => {
    if (month === 1) {
      setYear(year - 1);
      setMonth(12);
    } else {
      setMonth(month - 1);
    }
  };

  const goToNextMonth = () => {
    if (month === 12) {
      setYear(year + 1);
      setMonth(1);
    } else {
      setMonth(month + 1);
    }
  };

  // Deadline management
  const handleDeadlineChangeClick = () => {
    setShowDeadlineConfirm(true);
  };

  const handleDeadlineConfirm = () => {
    setShowDeadlineConfirm(false);
    // Set default deadline to end of month
    const defaultDate = new Date(year, month - 1, 20, 23, 59);
    setNewDeadline(defaultDate.toISOString().slice(0, 16));
    setShowDeadlinePicker(true);
  };

  const handleDeadlineSave = async () => {
    if (!newDeadline) return;

    try {
      setDeadlineLoading(true);
      const deadlineISO = new Date(newDeadline).toISOString();
      const result = await preferencesApi.updateDeadline(year, month, deadlineISO);
      setDeadline(result);
      setShowDeadlinePicker(false);
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to update deadline");
    } finally {
      setDeadlineLoading(false);
    }
  };

  // Edit modal handlers
  const openEditModal = async (doctor: Doctor) => {
    setSelectedDoctor(doctor);
    setEditModalOpen(true);
    setFormLoading(true);

    try {
      const data = await preferencesApi.getWorking(year, month, doctor.id);
      setPreferenceData(data);
      setFormData({
        unavailable_onsite_days: data.unavailable_onsite_days,
        unavailable_oncall_days: data.unavailable_oncall_days,
        preferred_onsite_days: data.preferred_onsite_days,
        preferred_oncall_days: data.preferred_oncall_days,
        min_onsite_total: data.min_onsite_total,
        max_onsite_total: data.max_onsite_total,
        target_onsite_total: data.target_onsite_total,
        min_oncall_total: data.min_oncall_total,
        max_oncall_total: data.max_oncall_total,
        target_oncall_total: data.target_oncall_total,
        max_onsite_weekends: data.max_onsite_weekends,
        target_onsite_weekends: data.target_onsite_weekends,
        max_oncall_weekends: data.max_oncall_weekends,
        target_oncall_weekends: data.target_oncall_weekends,
        preferred_onsite_weekdays: data.preferred_onsite_weekdays,
        preferred_oncall_weekdays: data.preferred_oncall_weekdays,
        avoid_onsite_weekdays: data.avoid_onsite_weekdays,
        avoid_oncall_weekdays: data.avoid_oncall_weekdays,
        allow_weekend_consecutive_onsite_oncall: data.allow_weekend_consecutive_onsite_oncall,
        preferred_partners: data.preferred_partners,
        comments: data.comments,
      });
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to load preferences");
      setEditModalOpen(false);
    } finally {
      setFormLoading(false);
    }
  };

  const closeEditModal = () => {
    setEditModalOpen(false);
    setSelectedDoctor(null);
    setPreferenceData(null);
    setFormData(getDefaultPreferences());
  };

  const handleSaveCheckpoint = async () => {
    if (!selectedDoctor) return;

    try {
      setSaveLoading(true);
      // First save working copy
      await preferencesApi.saveWorking(year, month, selectedDoctor.id, formData);
      // Then create checkpoint
      const result = await preferencesApi.createCheckpoint(year, month, selectedDoctor.id);
      setPreferenceData((prev) =>
        prev
          ? {
              ...prev,
              status: result.status,
              version_id: result.version_id,
              submitted_at: result.submitted_at,
              can_undo: result.can_undo,
              can_redo: result.can_redo,
            }
          : null
      );
      // Refresh summary
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to save");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleUndo = async () => {
    if (!selectedDoctor || !preferenceData?.can_undo) return;

    try {
      setSaveLoading(true);
      const result = await preferencesApi.revertLast(year, month, selectedDoctor.id);
      // Update form data with reverted values
      setFormData({
        unavailable_onsite_days: result.unavailable_onsite_days,
        unavailable_oncall_days: result.unavailable_oncall_days,
        preferred_onsite_days: result.preferred_onsite_days,
        preferred_oncall_days: result.preferred_oncall_days,
        min_onsite_total: result.min_onsite_total,
        max_onsite_total: result.max_onsite_total,
        target_onsite_total: result.target_onsite_total,
        min_oncall_total: result.min_oncall_total,
        max_oncall_total: result.max_oncall_total,
        target_oncall_total: result.target_oncall_total,
        max_onsite_weekends: result.max_onsite_weekends,
        target_onsite_weekends: result.target_onsite_weekends,
        max_oncall_weekends: result.max_oncall_weekends,
        target_oncall_weekends: result.target_oncall_weekends,
        preferred_onsite_weekdays: result.preferred_onsite_weekdays,
        preferred_oncall_weekdays: result.preferred_oncall_weekdays,
        avoid_onsite_weekdays: result.avoid_onsite_weekdays,
        avoid_oncall_weekdays: result.avoid_oncall_weekdays,
        allow_weekend_consecutive_onsite_oncall: result.allow_weekend_consecutive_onsite_oncall,
        preferred_partners: result.preferred_partners,
        comments: result.comments,
      });
      setPreferenceData((prev) =>
        prev
          ? {
              ...prev,
              can_undo: result.can_undo,
              can_redo: result.can_redo,
              version_id: result.version_id,
            }
          : null
      );
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Cannot undo");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleRedo = async () => {
    if (!selectedDoctor || !preferenceData?.can_redo) return;

    try {
      setSaveLoading(true);
      const result = await preferencesApi.revertNext(year, month, selectedDoctor.id);
      // Update form data with reverted values
      setFormData({
        unavailable_onsite_days: result.unavailable_onsite_days,
        unavailable_oncall_days: result.unavailable_oncall_days,
        preferred_onsite_days: result.preferred_onsite_days,
        preferred_oncall_days: result.preferred_oncall_days,
        min_onsite_total: result.min_onsite_total,
        max_onsite_total: result.max_onsite_total,
        target_onsite_total: result.target_onsite_total,
        min_oncall_total: result.min_oncall_total,
        max_oncall_total: result.max_oncall_total,
        target_oncall_total: result.target_oncall_total,
        max_onsite_weekends: result.max_onsite_weekends,
        target_onsite_weekends: result.target_onsite_weekends,
        max_oncall_weekends: result.max_oncall_weekends,
        target_oncall_weekends: result.target_oncall_weekends,
        preferred_onsite_weekdays: result.preferred_onsite_weekdays,
        preferred_oncall_weekdays: result.preferred_oncall_weekdays,
        avoid_onsite_weekdays: result.avoid_onsite_weekdays,
        avoid_oncall_weekdays: result.avoid_oncall_weekdays,
        allow_weekend_consecutive_onsite_oncall: result.allow_weekend_consecutive_onsite_oncall,
        preferred_partners: result.preferred_partners,
        comments: result.comments,
      });
      setPreferenceData((prev) =>
        prev
          ? {
              ...prev,
              can_undo: result.can_undo,
              can_redo: result.can_redo,
              version_id: result.version_id,
            }
          : null
      );
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Cannot redo");
    } finally {
      setSaveLoading(false);
    }
  };

  // Calendar day state helpers
  type DayState = "can" | "cant" | "want";

  const getDayState = (
    day: number,
    unavailableDays: number[],
    preferredDays: number[]
  ): DayState => {
    if (unavailableDays.includes(day)) return "cant";
    if (preferredDays.includes(day)) return "want";
    return "can";
  };

  const cycleDayState = (
    day: number,
    currentState: DayState,
    unavailableDays: number[],
    preferredDays: number[],
    setUnavailable: (days: number[]) => void,
    setPreferred: (days: number[]) => void
  ) => {
    if (currentState === "can") {
      // CAN -> WANT
      setPreferred([...preferredDays, day].sort((a, b) => a - b));
    } else if (currentState === "want") {
      // WANT -> CAN'T
      setPreferred(preferredDays.filter((d) => d !== day));
      setUnavailable([...unavailableDays, day].sort((a, b) => a - b));
    } else {
      // CAN'T -> CAN
      setUnavailable(unavailableDays.filter((d) => d !== day));
    }
  };

  // Weekday state helpers
  const getWeekdayState = (
    weekday: number,
    preferredWeekdays: number[],
    avoidWeekdays: number[]
  ): DayState => {
    if (avoidWeekdays.includes(weekday)) return "cant";
    if (preferredWeekdays.includes(weekday)) return "want";
    return "can";
  };

  const cycleWeekdayState = (
    weekday: number,
    currentState: DayState,
    preferredWeekdays: number[],
    avoidWeekdays: number[],
    setPreferred: (days: number[]) => void,
    setAvoid: (days: number[]) => void
  ) => {
    if (currentState === "can") {
      setPreferred([...preferredWeekdays, weekday].sort((a, b) => a - b));
    } else if (currentState === "want") {
      setPreferred(preferredWeekdays.filter((d) => d !== weekday));
      setAvoid([...avoidWeekdays, weekday].sort((a, b) => a - b));
    } else {
      setAvoid(avoidWeekdays.filter((d) => d !== weekday));
    }
  };

  const daysRemaining = getDaysRemaining(deadline?.deadline ?? null);
  const isPast = deadline?.status === "locked" || (daysRemaining !== null && daysRemaining < 0);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/admin")}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <h2 className="text-3xl font-bold">Manage Preferences</h2>
          </div>
          <Button onClick={handleDeadlineChangeClick}>
            <Calendar className="h-4 w-4 mr-2" />
            Change Deadline
          </Button>
        </div>

        {/* Month Picker */}
        <Card className="mb-6">
          <CardContent className="py-4">
            <div className="flex items-center justify-center space-x-4">
              <Button variant="outline" size="sm" onClick={goToPrevMonth}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-xl font-semibold min-w-[200px] text-center">
                {MONTH_NAMES[month - 1]} {year}
              </span>
              <Button variant="outline" size="sm" onClick={goToNextMonth}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Deadline Banner */}
        {deadline && (
          <Card className={`mb-6 ${isPast ? "bg-red-50 border-red-200" : "bg-blue-50 border-blue-200"}`}>
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <Clock className={`h-5 w-5 ${isPast ? "text-red-600" : "text-blue-600"}`} />
                  <div>
                    <span className={`font-semibold ${isPast ? "text-red-700" : "text-blue-700"}`}>
                      Status: {deadline.status === "locked" ? "Locked" : "Open"}
                    </span>
                    {deadline.deadline && (
                      <span className="ml-4 text-gray-600">
                        Deadline: {formatDate(deadline.deadline)}
                        {daysRemaining !== null && daysRemaining >= 0 && (
                          <span className="ml-2 text-sm">
                            ({daysRemaining} day{daysRemaining !== 1 ? "s" : ""} remaining)
                          </span>
                        )}
                      </span>
                    )}
                    {!deadline.deadline && (
                      <span className="ml-4 text-gray-500 italic">No deadline set</span>
                    )}
                  </div>
                </div>
                <div className="text-sm text-gray-500">
                  Timezone: {deadline.org_timezone}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Filters */}
        <Card className="mb-6">
          <CardContent className="pt-6">
            <div className="flex items-center space-x-4">
              <Label>Filter by Status:</Label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as any)}
                className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="all">All ({doctorsWithStatus.length})</option>
                <option value="submitted">
                  Submitted ({summary?.submitted.length ?? 0})
                </option>
                <option value="missing">
                  Missing ({summary?.missing.length ?? 0})
                </option>
              </select>
            </div>
          </CardContent>
        </Card>

        {/* Doctors Table */}
        <Card>
          <CardHeader>
            <CardTitle>Doctor Preferences ({filteredDoctors.length})</CardTitle>
            <CardDescription>
              View and manage preference submissions for {MONTH_NAMES[month - 1]} {year}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-center py-8">Loading...</div>
            ) : error ? (
              <div className="text-center py-8 text-red-600">{error}</div>
            ) : filteredDoctors.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No doctors found
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-3 px-4">#</th>
                      <th className="text-left py-3 px-4">Doctor Name</th>
                      <th className="text-left py-3 px-4">Role</th>
                      <th className="text-left py-3 px-4">Status</th>
                      <th className="text-right py-3 px-4">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDoctors.map((doctor, idx) => (
                      <tr
                        key={doctor.id}
                        className="border-b hover:bg-muted/50 cursor-pointer"
                        onClick={() => openEditModal(doctor)}
                      >
                        <td className="py-3 px-4">{idx + 1}</td>
                        <td className="py-3 px-4 font-medium">
                          {doctor.first_name} {doctor.last_name}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-1 text-xs rounded ${
                              doctor.role === "specialist"
                                ? "bg-blue-100 text-blue-700"
                                : "bg-green-100 text-green-700"
                            }`}
                          >
                            {doctor.role}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {doctor.preferenceStatus === "submitted" ? (
                            <span className="flex items-center text-green-600">
                              <CheckCircle className="h-4 w-4 mr-1" />
                              Submitted
                            </span>
                          ) : (
                            <span className="flex items-center text-red-600">
                              <XCircle className="h-4 w-4 mr-1" />
                              Missing
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              openEditModal(doctor);
                            }}
                          >
                            {doctor.preferenceStatus === "submitted" ? (
                              <Eye className="h-4 w-4" />
                            ) : (
                              <Pencil className="h-4 w-4" />
                            )}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Deadline Confirmation Dialog */}
        <AlertDialog open={showDeadlineConfirm} onOpenChange={setShowDeadlineConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <div className="flex items-center space-x-2">
                <AlertTriangle className="h-5 w-5 text-yellow-600" />
                <AlertDialogTitle>Change Deadline?</AlertDialogTitle>
              </div>
              <AlertDialogDescription>
                Are you sure you want to change the deadline for {MONTH_NAMES[month - 1]} {year}?
                All active doctors will receive an email notification about the new deadline.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleDeadlineConfirm}>
                Continue
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Deadline Picker Dialog */}
        <AlertDialog open={showDeadlinePicker} onOpenChange={setShowDeadlinePicker}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Set New Deadline</AlertDialogTitle>
              <AlertDialogDescription>
                Choose the deadline for preference submissions for {MONTH_NAMES[month - 1]} {year}.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="py-4">
              <Label htmlFor="deadline">Deadline Date & Time</Label>
              <Input
                id="deadline"
                type="datetime-local"
                value={newDeadline}
                onChange={(e) => setNewDeadline(e.target.value)}
                className="mt-2"
              />
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deadlineLoading}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleDeadlineSave} disabled={deadlineLoading || !newDeadline}>
                {deadlineLoading ? "Saving..." : "Save Deadline"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Edit Modal */}
        {editModalOpen && selectedDoctor && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 overflow-y-auto py-8">
            <Card className="w-full max-w-4xl mx-4 max-h-[90vh] overflow-y-auto">
              <CardHeader className="sticky top-0 bg-white z-10 border-b">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>
                      Edit Preferences: {selectedDoctor.first_name} {selectedDoctor.last_name}
                    </CardTitle>
                    <CardDescription>
                      {MONTH_NAMES[month - 1]} {year}
                      {preferenceData && (
                        <span className="ml-4">
                          Status:{" "}
                          <span
                            className={
                              preferenceData.status === "submitted"
                                ? "text-green-600"
                                : "text-red-600"
                            }
                          >
                            {preferenceData.status}
                          </span>
                        </span>
                      )}
                    </CardDescription>
                  </div>
                  <Button variant="ghost" size="sm" onClick={closeEditModal}>
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="pt-6">
                {formLoading ? (
                  <div className="text-center py-8">Loading preferences...</div>
                ) : (
                  <div className="space-y-8">
                    {/* A) Availability Calendar */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">A) Availability Calendar</h3>
                      <p className="text-sm text-muted-foreground mb-4">
                        Click on a day to cycle through: CAN (gray) → WANT (green) → CAN'T (red)
                      </p>

                      {/* On-site Calendar */}
                      <div className="mb-6">
                        <h4 className="font-medium mb-2">On-site Duty</h4>
                        <div className="grid grid-cols-7 gap-1">
                          {WEEKDAY_NAMES.map((day) => (
                            <div key={day} className="text-center text-xs font-medium text-gray-500 py-1">
                              {day}
                            </div>
                          ))}
                          {/* Empty cells for first week offset */}
                          {Array.from({ length: getFirstDayOfMonth(year, month) }).map((_, i) => (
                            <div key={`empty-${i}`} className="h-10" />
                          ))}
                          {/* Day cells */}
                          {Array.from({ length: getDaysInMonth(year, month) }).map((_, i) => {
                            const day = i + 1;
                            const state = getDayState(
                              day,
                              formData.unavailable_onsite_days,
                              formData.preferred_onsite_days
                            );
                            return (
                              <button
                                key={day}
                                type="button"
                                onClick={() =>
                                  cycleDayState(
                                    day,
                                    state,
                                    formData.unavailable_onsite_days,
                                    formData.preferred_onsite_days,
                                    (days) =>
                                      setFormData({ ...formData, unavailable_onsite_days: days }),
                                    (days) =>
                                      setFormData({ ...formData, preferred_onsite_days: days })
                                  )
                                }
                                className={`h-10 rounded text-sm font-medium transition-colors ${
                                  state === "cant"
                                    ? "bg-red-100 text-red-700 hover:bg-red-200"
                                    : state === "want"
                                    ? "bg-green-100 text-green-700 hover:bg-green-200"
                                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                                }`}
                              >
                                {day}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* On-call Calendar */}
                      <div>
                        <h4 className="font-medium mb-2">On-call Shift</h4>
                        <div className="grid grid-cols-7 gap-1">
                          {WEEKDAY_NAMES.map((day) => (
                            <div key={day} className="text-center text-xs font-medium text-gray-500 py-1">
                              {day}
                            </div>
                          ))}
                          {Array.from({ length: getFirstDayOfMonth(year, month) }).map((_, i) => (
                            <div key={`empty-oncall-${i}`} className="h-10" />
                          ))}
                          {Array.from({ length: getDaysInMonth(year, month) }).map((_, i) => {
                            const day = i + 1;
                            const state = getDayState(
                              day,
                              formData.unavailable_oncall_days,
                              formData.preferred_oncall_days
                            );
                            return (
                              <button
                                key={day}
                                type="button"
                                onClick={() =>
                                  cycleDayState(
                                    day,
                                    state,
                                    formData.unavailable_oncall_days,
                                    formData.preferred_oncall_days,
                                    (days) =>
                                      setFormData({ ...formData, unavailable_oncall_days: days }),
                                    (days) =>
                                      setFormData({ ...formData, preferred_oncall_days: days })
                                  )
                                }
                                className={`h-10 rounded text-sm font-medium transition-colors ${
                                  state === "cant"
                                    ? "bg-red-100 text-red-700 hover:bg-red-200"
                                    : state === "want"
                                    ? "bg-green-100 text-green-700 hover:bg-green-200"
                                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                                }`}
                              >
                                {day}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </div>

                    {/* B) Shift Counts */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">B) How Many Shifts</h3>
                      <div className="grid grid-cols-3 gap-4">
                        <div></div>
                        <div className="text-center font-medium">Target</div>
                        <div className="text-center font-medium">Maximum</div>

                        <div className="font-medium">On-site Total</div>
                        <Input
                          type="number"
                          min="0"
                          value={formData.target_onsite_total ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              target_onsite_total: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />
                        <Input
                          type="number"
                          min="0"
                          value={formData.max_onsite_total ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              max_onsite_total: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />

                        <div className="font-medium">On-call Total</div>
                        <Input
                          type="number"
                          min="0"
                          value={formData.target_oncall_total ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              target_oncall_total: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />
                        <Input
                          type="number"
                          min="0"
                          value={formData.max_oncall_total ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              max_oncall_total: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />

                        <div className="font-medium text-sm text-gray-600">On-site Weekends</div>
                        <Input
                          type="number"
                          min="0"
                          value={formData.target_onsite_weekends ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              target_onsite_weekends: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />
                        <Input
                          type="number"
                          min="0"
                          value={formData.max_onsite_weekends ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              max_onsite_weekends: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />

                        <div className="font-medium text-sm text-gray-600">On-call Weekends</div>
                        <Input
                          type="number"
                          min="0"
                          value={formData.target_oncall_weekends ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              target_oncall_weekends: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />
                        <Input
                          type="number"
                          min="0"
                          value={formData.max_oncall_weekends ?? ""}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              max_oncall_weekends: e.target.value ? parseInt(e.target.value) : null,
                            })
                          }
                          placeholder="-"
                        />
                      </div>
                    </div>

                    {/* C) Weekday Patterns */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">C) Preferred Days of the Week</h3>
                      <p className="text-sm text-muted-foreground mb-4">
                        Click to cycle: Neutral (gray) → Prefer (green) → Avoid (red)
                      </p>

                      <div className="space-y-4">
                        <div>
                          <h4 className="font-medium mb-2">On-site</h4>
                          <div className="flex space-x-2">
                            {WEEKDAY_NAMES.map((name, idx) => {
                              const state = getWeekdayState(
                                idx,
                                formData.preferred_onsite_weekdays,
                                formData.avoid_onsite_weekdays
                              );
                              return (
                                <button
                                  key={idx}
                                  type="button"
                                  onClick={() =>
                                    cycleWeekdayState(
                                      idx,
                                      state,
                                      formData.preferred_onsite_weekdays,
                                      formData.avoid_onsite_weekdays,
                                      (days) =>
                                        setFormData({ ...formData, preferred_onsite_weekdays: days }),
                                      (days) =>
                                        setFormData({ ...formData, avoid_onsite_weekdays: days })
                                    )
                                  }
                                  className={`w-12 h-10 rounded text-sm font-medium transition-colors ${
                                    state === "cant"
                                      ? "bg-red-100 text-red-700 hover:bg-red-200"
                                      : state === "want"
                                      ? "bg-green-100 text-green-700 hover:bg-green-200"
                                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                                  }`}
                                >
                                  {name}
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        <div>
                          <h4 className="font-medium mb-2">On-call</h4>
                          <div className="flex space-x-2">
                            {WEEKDAY_NAMES.map((name, idx) => {
                              const state = getWeekdayState(
                                idx,
                                formData.preferred_oncall_weekdays,
                                formData.avoid_oncall_weekdays
                              );
                              return (
                                <button
                                  key={idx}
                                  type="button"
                                  onClick={() =>
                                    cycleWeekdayState(
                                      idx,
                                      state,
                                      formData.preferred_oncall_weekdays,
                                      formData.avoid_oncall_weekdays,
                                      (days) =>
                                        setFormData({ ...formData, preferred_oncall_weekdays: days }),
                                      (days) =>
                                        setFormData({ ...formData, avoid_oncall_weekdays: days })
                                    )
                                  }
                                  className={`w-12 h-10 rounded text-sm font-medium transition-colors ${
                                    state === "cant"
                                      ? "bg-red-100 text-red-700 hover:bg-red-200"
                                      : state === "want"
                                      ? "bg-green-100 text-green-700 hover:bg-green-200"
                                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                                  }`}
                                >
                                  {name}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* D) Weekend Rule */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">D) Weekend Rest Rule Exception</h3>
                      <div className="flex items-center space-x-2">
                        <input
                          type="checkbox"
                          id="weekend_rule"
                          checked={formData.allow_weekend_consecutive_onsite_oncall}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              allow_weekend_consecutive_onsite_oncall: e.target.checked,
                            })
                          }
                          className="h-4 w-4"
                        />
                        <Label htmlFor="weekend_rule">
                          I am OK with an intense weekend (consecutive on-site + on-call)
                        </Label>
                      </div>
                    </div>

                    {/* E) Preferred Partners */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">E) Preferred Colleagues</h3>
                      <p className="text-sm text-muted-foreground mb-2">
                        Select doctors you prefer to work with (optional)
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {doctors
                          .filter((d) => d.id !== selectedDoctor.id)
                          .map((doctor) => {
                            const isSelected = formData.preferred_partners.includes(doctor.id);
                            return (
                              <button
                                key={doctor.id}
                                type="button"
                                onClick={() => {
                                  if (isSelected) {
                                    setFormData({
                                      ...formData,
                                      preferred_partners: formData.preferred_partners.filter(
                                        (id) => id !== doctor.id
                                      ),
                                    });
                                  } else {
                                    setFormData({
                                      ...formData,
                                      preferred_partners: [...formData.preferred_partners, doctor.id],
                                    });
                                  }
                                }}
                                className={`px-3 py-1 rounded-full text-sm transition-colors ${
                                  isSelected
                                    ? "bg-blue-100 text-blue-700 border border-blue-300"
                                    : "bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200"
                                }`}
                              >
                                {doctor.first_name} {doctor.last_name}
                              </button>
                            );
                          })}
                      </div>
                    </div>

                    {/* F) Comments */}
                    <div>
                      <h3 className="text-lg font-semibold mb-4">F) Comments</h3>
                      <textarea
                        value={formData.comments ?? ""}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            comments: e.target.value || null,
                          })
                        }
                        placeholder="Any additional notes for the coordinator..."
                        className="w-full h-24 rounded-md border border-input bg-background px-3 py-2 text-sm"
                      />
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center justify-between pt-4 border-t">
                      <div className="flex space-x-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleUndo}
                          disabled={!preferenceData?.can_undo || saveLoading}
                        >
                          <Undo2 className="h-4 w-4 mr-1" />
                          Undo
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleRedo}
                          disabled={!preferenceData?.can_redo || saveLoading}
                        >
                          <Redo2 className="h-4 w-4 mr-1" />
                          Redo
                        </Button>
                      </div>
                      <div className="flex space-x-2">
                        <Button variant="outline" onClick={closeEditModal} disabled={saveLoading}>
                          Cancel
                        </Button>
                        <Button onClick={handleSaveCheckpoint} disabled={saveLoading}>
                          <Save className="h-4 w-4 mr-1" />
                          {saveLoading ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
};
