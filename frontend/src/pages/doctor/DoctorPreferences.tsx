import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../../components/shared/Header";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  PreferencesEditor,
  getDefaultPreferences,
  MONTH_NAMES,
  formatDate,
  getTimeRemaining,
} from "../../components/preferences";
import {
  validatePreferences,
  type ValidationError,
} from "../../components/preferences/validation";
import { useUndoRedo } from "../../hooks/useUndoRedo";
import { useLocalStorageDraft } from "../../hooks/useLocalStorageDraft";
import {
  preferencesApi,
  doctorPreferencesApi,
  doctorsApi,
} from "../../services/api";
import type {
  Doctor,
  PreferencesDeadlineRead,
  PreferenceWorkingRead,
  PreferenceWorkingPut,
} from "../../types";
import { ArrowLeft, ChevronLeft, ChevronRight, Clock } from "lucide-react";

export const DoctorPreferences = () => {
  const navigate = useNavigate();

  // Period state
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  // Data state
  const [preferenceData, setPreferenceData] =
    useState<PreferenceWorkingRead | null>(null);
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(
    null
  );
  const [colleagues, setColleagues] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>(
    []
  );

  // Client-side undo/redo
  const undoRedo = useUndoRedo<PreferenceWorkingPut>(getDefaultPreferences(), {
    maxHistory: 50,
  });

  // LocalStorage draft management
  const draft = useLocalStorageDraft(year, month, deadline?.deadline ?? null);

  // Debounce timer ref for autosave
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Helper to convert API response to form data
  const apiToFormData = (data: PreferenceWorkingRead): PreferenceWorkingPut => ({
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
    allow_weekend_consecutive_onsite_oncall:
      data.allow_weekend_consecutive_onsite_oncall,
    preferred_partners: data.preferred_partners,
    comments: data.comments,
  });

  // Fetch all data for period
  const fetchData = async () => {
    try {
      setLoading(true);
      setError("");

      const [prefsRes, deadlineRes, doctorsRes] = await Promise.all([
        doctorPreferencesApi.getMyPreferences(year, month),
        preferencesApi.getDeadline(year, month),
        doctorsApi.list({ size: 200, is_active: "true" }),
      ]);

      setPreferenceData(prefsRes);
      setDeadline(deadlineRes);
      setColleagues(doctorsRes.items);

      // Check for localStorage draft first
      const savedDraft = draft.loadDraft(prefsRes.doctor_id, {
        deleteIfExpired: true,
      });
      let initialData: PreferenceWorkingPut;

      if (savedDraft) {
        initialData = savedDraft;
        draft.setRestoredFromDraft(true);
      } else {
        initialData = apiToFormData(prefsRes);
        draft.setRestoredFromDraft(false);
      }

      // Initialize undo/redo stack
      undoRedo.reset(initialData);

      // Validate initial data
      const result = validatePreferences(initialData, year, month);
      setValidationErrors(result.errors);
    } catch (err: any) {
      setError(err.response?.data?.detail?.detail || "Failed to load data");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Clear autosave timer on period change
    return () => {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
      }
    };
  }, [year, month]);

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
        if (preferenceData) {
          draft.saveDraft(preferenceData.doctor_id, newData);
        }
      }, 1000);
    },
    [undoRedo, draft, preferenceData, year, month]
  );

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

  // Save checkpoint
  const handleSaveCheckpoint = async () => {
    if (!preferenceData) return;

    // Block save if deadline has passed (locked)
    if (deadline?.status === "locked") {
      alert("Cannot save: deadline has passed");
      return;
    }

    // Block save if validation errors
    if (validationErrors.length > 0) {
      alert("Please fix validation errors before saving");
      return;
    }

    try {
      setSaveLoading(true);
      // First save working copy
      await doctorPreferencesApi.saveMyWorking(year, month, undoRedo.current);
      // Then create checkpoint
      const result = await doctorPreferencesApi.createMyCheckpoint(year, month);
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
      draft.clearDraft(preferenceData.doctor_id);
      draft.setRestoredFromDraft(false);
    } catch (err: any) {
      alert(err.response?.data?.detail?.detail || "Failed to save");
    } finally {
      setSaveLoading(false);
    }
  };

  const timeRemaining = getTimeRemaining(deadline?.deadline ?? null);
  const isPast =
    deadline?.status === "locked" || (timeRemaining?.isPast ?? false);
  const isReadOnly =
    preferenceData?.period_status === "past" || deadline?.status === "locked";

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center space-x-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/doctor")}
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
          <h2 className="text-3xl font-bold">My Preferences</h2>
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
          <Card
            className={`mb-6 ${
              isPast
                ? "bg-red-50 border-red-200"
                : "bg-blue-50 border-blue-200"
            }`}
          >
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <Clock
                    className={`h-5 w-5 ${
                      isPast ? "text-red-600" : "text-blue-600"
                    }`}
                  />
                  <div>
                    <span
                      className={`font-semibold ${
                        isPast ? "text-red-700" : "text-blue-700"
                      }`}
                    >
                      Status:{" "}
                      {deadline.status === "locked" ? "Locked" : "Open"}
                    </span>
                    {deadline.deadline && (
                      <span className="ml-4 text-gray-600">
                        Deadline: {formatDate(deadline.deadline)}
                        {timeRemaining && !timeRemaining.isPast && (
                          <span className="ml-2 text-sm">
                            ({timeRemaining.days} day
                            {timeRemaining.days !== 1 ? "s" : ""} remaining)
                          </span>
                        )}
                      </span>
                    )}
                    {!deadline.deadline && (
                      <span className="ml-4 text-gray-500 italic">
                        No deadline set
                      </span>
                    )}
                  </div>
                </div>
                {preferenceData && (
                  <div
                    className={`px-3 py-1 rounded-full text-sm font-medium ${
                      preferenceData.status === "submitted"
                        ? "bg-green-100 text-green-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {preferenceData.status === "submitted"
                      ? "Submitted"
                      : "Not Submitted"}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Main Content */}
        <Card>
          <CardHeader>
            <CardTitle>
              Preferences for {MONTH_NAMES[month - 1]} {year}
              {draft.isRestoredFromDraft && (
                <span className="ml-2 text-amber-600 text-sm font-normal">
                  (Restored from draft)
                </span>
              )}
            </CardTitle>
            <CardDescription>
              {isReadOnly
                ? "This period is read-only"
                : "Set your availability and shift preferences"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-center py-8">Loading preferences...</div>
            ) : error ? (
              <div className="text-center py-8 text-red-600">{error}</div>
            ) : preferenceData ? (
              <PreferencesEditor
                mode="doctor"
                doctorId={preferenceData.doctor_id}
                doctorName=""
                year={year}
                month={month}
                colleagues={colleagues}
                deadline={deadline}
                formData={undoRedo.current}
                onFormDataChange={handleFormDataChange}
                onSave={handleSaveCheckpoint}
                onUndo={undoRedo.undo}
                onRedo={undoRedo.redo}
                canUndo={undoRedo.canUndo}
                canRedo={undoRedo.canRedo}
                // No server-side version navigation for doctor
                canPreviousVersion={false}
                canNextVersion={false}
                status={preferenceData.status}
                periodStatus={preferenceData.period_status}
                validationErrors={validationErrors}
                isSaving={saveLoading}
              />
            ) : null}
          </CardContent>
        </Card>
      </main>
    </div>
  );
};
