import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
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
import { Calendar as CalendarWidget } from "../../components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { PreferencesEditor, getDefaultPreferences, MONTH_NAMES, formatDate, getTimeRemaining } from "../../components/preferences";
import { validatePreferences, type ValidationError } from "../../components/preferences/validation";
import { useUndoRedo } from "../../hooks/useUndoRedo";
import { useLocalStorageDraft } from "../../hooks/useLocalStorageDraft";
import { preferencesApi, doctorsApi } from "../../services/api";
import { enUS } from "date-fns/locale";
import { format } from "date-fns";
import type {
  Doctor,
  PreferencesSummaryRead,
  PreferencesDeadlineRead,
  PreferenceWorkingRead,
  PreferenceWorkingPut,
  PreferenceRevertRead,
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
  X,
  AlertTriangle,
  Search,
  RotateCcw,
  CalendarIcon,
} from "lucide-react";

export const PreferencesManagement = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Period state (initialize from URL params if present, default to next month)
  const now = new Date();
  const _nextMonth = now.getMonth() + 2; // getMonth() is 0-based, +2 = next month
  const _nextMonthYear = _nextMonth > 12 ? now.getFullYear() + 1 : now.getFullYear();
  const _nextMonthNormalized = _nextMonth > 12 ? 1 : _nextMonth;
  const [year, setYear] = useState(() => {
    const p = searchParams.get("year");
    return p ? parseInt(p, 10) : _nextMonthYear;
  });
  const [month, setMonth] = useState(() => {
    const p = searchParams.get("month");
    return p ? parseInt(p, 10) : _nextMonthNormalized;
  });

  // Data state
  const [summary, setSummary] = useState<PreferencesSummaryRead | null>(null);
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter state
  const [statusFilter, setStatusFilter] = useState<"all" | "submitted" | "missing">("all");
  const [roleFilter, setRoleFilter] = useState<"all" | "specialist" | "resident">("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Deadline dialog state
  const [showDeadlineConfirm, setShowDeadlineConfirm] = useState(false);
  const [showDeadlinePicker, setShowDeadlinePicker] = useState(false);
  const [newDeadlineDate, setNewDeadlineDate] = useState<Date | undefined>(undefined);
  const [newDeadlineHour, setNewDeadlineHour] = useState("23");
  const [newDeadlineMinute, setNewDeadlineMinute] = useState("59");
  const [deadlineLoading, setDeadlineLoading] = useState(false);

  // Edit modal state
  const [selectedDoctor, setSelectedDoctor] = useState<Doctor | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [preferenceData, setPreferenceData] = useState<PreferenceWorkingRead | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);

  // Client-side undo/redo (resets when modal closes)
  const undoRedo = useUndoRedo<PreferenceWorkingPut>(getDefaultPreferences(), { maxHistory: 50 });

  // LocalStorage draft management
  const draft = useLocalStorageDraft(
    year,
    month,
    deadline?.deadline ?? null
  );

  // Debounce timer ref for autosave
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Auto-open edit modal if doctor_id is in URL params
  const doctorIdParam = searchParams.get("doctor_id");
  useEffect(() => {
    if (!doctorIdParam || loading || doctors.length === 0) return;
    const doctorId = parseInt(doctorIdParam, 10);
    const doctor = doctors.find((d) => d.id === doctorId);
    if (doctor && !editModalOpen) {
      openEditModal(doctor);
      // Clear the param so it doesn't re-trigger
      const next = new URLSearchParams(searchParams);
      next.delete("doctor_id");
      setSearchParams(next, { replace: true });
    }
  }, [doctorIdParam, loading, doctors]);

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
    return doctorsWithStatus.filter((d) => {
      // Status filter
      if (statusFilter !== "all" && d.preferenceStatus !== statusFilter) return false;
      // Role filter
      if (roleFilter !== "all" && d.role !== roleFilter) return false;
      // Search filter
      if (searchQuery) {
        const fullName = `${d.first_name} ${d.last_name}`.toLowerCase();
        if (!fullName.includes(searchQuery.toLowerCase())) return false;
      }
      return true;
    });
  }, [doctorsWithStatus, statusFilter, roleFilter, searchQuery]);

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

  // Handle form data changes with validation and autosave
  const handleFormDataChange = useCallback(
    (newData: PreferenceWorkingPut) => {
      // Update undo/redo stack
      undoRedo.set(newData);

      // Validate
      const result = validatePreferences(newData, year, month);
      setValidationErrors(result.errors);

      // Debounced autosave to localStorage
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
      }
      autosaveTimerRef.current = setTimeout(() => {
        if (selectedDoctor) {
          draft.saveDraft(selectedDoctor.id, newData);
        }
      }, 1000);
    },
    [undoRedo, draft, selectedDoctor, year, month]
  );

  // Deadline management
  const handleDeadlineChangeClick = () => {
    setShowDeadlineConfirm(true);
  };

  const handleDeadlineConfirm = () => {
    setShowDeadlineConfirm(false);
    // Set default deadline to 15th of the current month at 23:59
    const now = new Date();
    setNewDeadlineDate(new Date(now.getFullYear(), now.getMonth(), 15));
    setNewDeadlineHour("23");
    setNewDeadlineMinute("59");
    setShowDeadlinePicker(true);
  };

  const handleDeadlineSave = async () => {
    if (!newDeadlineDate) return;

    try {
      setDeadlineLoading(true);
      const combined = new Date(newDeadlineDate);
      combined.setHours(parseInt(newDeadlineHour, 10), parseInt(newDeadlineMinute, 10), 0, 0);
      const deadlineISO = combined.toISOString();
      const result = await preferencesApi.updateDeadline(year, month, deadlineISO);
      setDeadline(result);
      setShowDeadlinePicker(false);
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to update deadline");
    } finally {
      setDeadlineLoading(false);
    }
  };

  // Helper to convert API response to form data (accepts any type with editable fields)
  const apiToFormData = (data: PreferenceWorkingRead | PreferenceRevertRead): PreferenceWorkingPut => ({
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

  // Edit modal handlers
  const openEditModal = async (doctor: Doctor) => {
    setSelectedDoctor(doctor);
    setEditModalOpen(true);
    setFormLoading(true);
    setValidationErrors([]);

    try {
      const data = await preferencesApi.getWorking(year, month, doctor.id);
      setPreferenceData(data);

      // Check for localStorage draft first (pass doctor.id directly)
      const savedDraft = draft.loadDraft(doctor.id);
      let initialData: PreferenceWorkingPut;

      if (savedDraft) {
        // Use saved draft
        initialData = savedDraft;
        draft.setRestoredFromDraft(true);
      } else {
        // Use server data
        initialData = apiToFormData(data);
        draft.setRestoredFromDraft(false);
      }

      // Initialize undo/redo stack with the initial data
      undoRedo.reset(initialData);

      // Validate initial data
      const result = validatePreferences(initialData, year, month);
      setValidationErrors(result.errors);
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to load preferences");
      setEditModalOpen(false);
    } finally {
      setFormLoading(false);
    }
  };

  const closeEditModal = () => {
    // Clear autosave timer
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }

    setEditModalOpen(false);
    setSelectedDoctor(null);
    setPreferenceData(null);
    setValidationErrors([]);

    // Reset undo/redo stack
    undoRedo.reset(getDefaultPreferences());

    // Reset draft state
    draft.setRestoredFromDraft(false);
  };

  const handleSaveCheckpoint = async () => {
    if (!selectedDoctor) return;

    // Block save if validation errors
    if (validationErrors.length > 0) {
      alert("Please fix validation errors before saving");
      return;
    }

    try {
      setSaveLoading(true);
      // First save working copy
      await preferencesApi.saveWorking(year, month, selectedDoctor.id, undoRedo.current);
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

      // Clear localStorage draft on successful save
      draft.clearDraft(selectedDoctor.id);
      draft.setRestoredFromDraft(false);

      // Refresh summary
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to save");
    } finally {
      setSaveLoading(false);
    }
  };

  // Server-side version navigation (Previous/Next)
  const handlePreviousVersion = async () => {
    if (!selectedDoctor || !preferenceData?.can_undo) return;

    try {
      setSaveLoading(true);
      const result = await preferencesApi.revertLast(year, month, selectedDoctor.id);
      // Update undo/redo stack with reverted values (resets local history)
      const newFormData = apiToFormData(result);
      undoRedo.reset(newFormData);

      // Validate new data
      const validationResult = validatePreferences(newFormData, year, month);
      setValidationErrors(validationResult.errors);

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
      alert(err.response?.data?.detail?.detail || "Cannot go to previous version");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleNextVersion = async () => {
    if (!selectedDoctor || !preferenceData?.can_redo) return;

    try {
      setSaveLoading(true);
      const result = await preferencesApi.revertNext(year, month, selectedDoctor.id);
      // Update undo/redo stack with reverted values (resets local history)
      const newFormData = apiToFormData(result);
      undoRedo.reset(newFormData);

      // Validate new data
      const validationResult = validatePreferences(newFormData, year, month);
      setValidationErrors(validationResult.errors);

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
      alert(err.response?.data?.detail?.detail || "Cannot go to next version");
    } finally {
      setSaveLoading(false);
    }
  };

  const timeRemaining = getTimeRemaining(deadline?.deadline ?? null);
  const isPast = deadline?.status === "locked" || (timeRemaining?.isPast ?? false);

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminHeader />
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
                        {timeRemaining && !timeRemaining.isPast && (
                          <span className="ml-2 text-sm">
                            ({timeRemaining.days} day{timeRemaining.days !== 1 ? "s" : ""} remaining)
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
            <div className="flex flex-wrap items-center gap-4">
              {/* Search */}
              <div className="flex items-center space-x-2">
                <Search className="h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search by name..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-48"
                />
              </div>

              {/* Status filter */}
              <div className="flex items-center space-x-2">
                <Label>Status:</Label>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as any)}
                  className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="submitted">Submitted</option>
                  <option value="missing">Missing</option>
                </select>
              </div>

              {/* Role filter */}
              <div className="flex items-center space-x-2">
                <Label>Role:</Label>
                <select
                  value={roleFilter}
                  onChange={(e) => setRoleFilter(e.target.value as any)}
                  className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="specialist">Specialist</option>
                  <option value="resident">Resident</option>
                </select>
              </div>

              {/* Clear filters */}
              {(searchQuery || statusFilter !== "all" || roleFilter !== "all") && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSearchQuery("");
                    setStatusFilter("all");
                    setRoleFilter("all");
                  }}
                >
                  <RotateCcw className="h-4 w-4 mr-1" />
                  Clear
                </Button>
              )}
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
            <div className="py-4 space-y-4">
              <div>
                <Label>Date</Label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-start text-left font-normal mt-2"
                    >
                      <CalendarIcon className="mr-2 h-4 w-4" />
                      {newDeadlineDate
                        ? format(newDeadlineDate, "MMMM d, yyyy", { locale: enUS })
                        : "Pick a date"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <CalendarWidget
                      mode="single"
                      selected={newDeadlineDate}
                      onSelect={setNewDeadlineDate}
                      locale={enUS}
                      initialFocus
                    />
                  </PopoverContent>
                </Popover>
              </div>
              <div>
                <Label>Time</Label>
                <div className="flex items-center gap-2 mt-2">
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={2}
                    placeholder="HH"
                    value={newDeadlineHour}
                    onChange={(e) => {
                      const raw = e.target.value.replace(/\D/g, "");
                      if (raw === "") { setNewDeadlineHour(""); return; }
                      const n = Math.min(23, Math.max(0, parseInt(raw, 10)));
                      setNewDeadlineHour(String(n));
                    }}
                    onBlur={() => {
                      if (newDeadlineHour === "") setNewDeadlineHour("0");
                      else setNewDeadlineHour(newDeadlineHour.padStart(2, "0"));
                    }}
                    className="w-16 text-center"
                  />
                  <span className="text-lg font-medium">:</span>
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={2}
                    placeholder="MM"
                    value={newDeadlineMinute}
                    onChange={(e) => {
                      const raw = e.target.value.replace(/\D/g, "");
                      if (raw === "") { setNewDeadlineMinute(""); return; }
                      const n = Math.min(59, Math.max(0, parseInt(raw, 10)));
                      setNewDeadlineMinute(String(n));
                    }}
                    onBlur={() => {
                      if (newDeadlineMinute === "") setNewDeadlineMinute("0");
                      else setNewDeadlineMinute(newDeadlineMinute.padStart(2, "0"));
                    }}
                    className="w-16 text-center"
                  />
                </div>
              </div>
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deadlineLoading}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleDeadlineSave} disabled={deadlineLoading || !newDeadlineDate}>
                {deadlineLoading ? "Saving..." : "Save Deadline"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Edit Modal with PreferencesEditor */}
        {editModalOpen && selectedDoctor && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 overflow-y-auto py-8">
            <Card className="w-full max-w-5xl mx-4 max-h-[90vh] overflow-y-auto">
              <CardHeader className="sticky top-0 bg-white z-10 border-b">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>
                      Edit Preferences: {selectedDoctor.first_name} {selectedDoctor.last_name}
                    </CardTitle>
                    <CardDescription>
                      {MONTH_NAMES[month - 1]} {year}
                      {draft.isRestoredFromDraft && (
                        <span className="ml-2 text-amber-600 font-medium">
                          (Restored from draft)
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
                  <PreferencesEditor
                    mode="admin"
                    doctorId={selectedDoctor.id}
                    doctorName={`${selectedDoctor.first_name} ${selectedDoctor.last_name}`}
                    year={year}
                    month={month}
                    colleagues={doctors}
                    deadline={deadline}
                    formData={undoRedo.current}
                    onFormDataChange={handleFormDataChange}
                    onSave={handleSaveCheckpoint}
                    onUndo={undoRedo.undo}
                    onRedo={undoRedo.redo}
                    canUndo={undoRedo.canUndo}
                    canRedo={undoRedo.canRedo}
                    onPreviousVersion={handlePreviousVersion}
                    onNextVersion={handleNextVersion}
                    canPreviousVersion={preferenceData?.can_undo ?? false}
                    canNextVersion={preferenceData?.can_redo ?? false}
                    status={preferenceData?.status ?? "missing"}
                    periodStatus={preferenceData?.period_status}
                    validationErrors={validationErrors}
                    isSaving={saveLoading}
                  />
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
};
