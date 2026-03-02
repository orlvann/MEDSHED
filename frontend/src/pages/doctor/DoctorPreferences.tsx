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
  DoctorMini,
  PreferencesDeadlineRead,
  PreferenceWorkingRead,
  PreferenceWorkingPut,
  PreferenceRevertRead,
} from "../../types";
import { ArrowLeft, ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { InfoTooltip } from "../../components/preferences/InfoTooltip";

// Calculate next month for preferences (preferences are always for NEXT month)
const getInitialPeriod = () => {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth() + 2; // +2 because getMonth() is 0-based and we need NEXT month

  if (month > 12) {
    month = 1;
    year += 1;
  }

  return { year, month };
};

export const DoctorPreferences = () => {
  const navigate = useNavigate();

  // Period state - start with NEXT month
  const initialPeriod = getInitialPeriod();
  const [year, setYear] = useState(initialPeriod.year);
  const [month, setMonth] = useState(initialPeriod.month);

  // Data state
  const [preferenceData, setPreferenceData] =
    useState<PreferenceWorkingRead | null>(null);
  const [deadline, setDeadline] = useState<PreferencesDeadlineRead | null>(
    null
  );
  const [colleagues, setColleagues] = useState<DoctorMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
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
  const apiToFormData = (
    data: PreferenceWorkingRead
  ): PreferenceWorkingPut => ({
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

      const [prefsRes, deadlineRes, doctorNames] = await Promise.all([
        doctorPreferencesApi.getMyPreferences(year, month),
        preferencesApi.getDeadline(year, month),
        doctorsApi.listNames(),
      ]);

      setPreferenceData(prefsRes);
      setDeadline(deadlineRes);
      setColleagues(doctorNames);

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

    setSaveError(null);

    // Block save if deadline has passed (locked)
    if (deadline?.status === "locked") {
      setSaveError("Cannot save: deadline has passed");
      return;
    }

    // Block save if validation errors
    if (validationErrors.length > 0) {
      setSaveError("Please fix validation errors before saving");
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
      const detail = err.response?.data?.detail;
      let msg = "Failed to save";
      if (Array.isArray(detail)) {
        msg = detail[0]?.msg || msg;
      } else if (detail?.code) {
        msg = detail.detail || detail.code;
        if (detail.context?.field) {
          setValidationErrors((prev) => [
            ...prev.filter((e) => e.field !== detail.context.field),
            { field: detail.context.field, message: msg },
          ]);
        }
      }
      setSaveError(msg);
    } finally {
      setSaveLoading(false);
    }
  };

  // Helper to convert API response to form data
  const apiToRevertFormData = (
    data: PreferenceRevertRead
  ): PreferenceWorkingPut => ({
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

  // Server-side version navigation (Previous/Next)
  const handlePreviousVersion = async () => {
    if (!preferenceData?.can_undo) return;

    try {
      setSaveLoading(true);
      const result = await doctorPreferencesApi.revertMyLast(year, month);
      const newFormData = apiToRevertFormData(result);
      undoRedo.reset(newFormData);

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
      alert(
        err.response?.data?.detail?.detail || "Cannot go to previous version"
      );
    } finally {
      setSaveLoading(false);
    }
  };

  const handleNextVersion = async () => {
    if (!preferenceData?.can_redo) return;

    try {
      setSaveLoading(true);
      const result = await doctorPreferencesApi.revertMyNext(year, month);
      const newFormData = apiToRevertFormData(result);
      undoRedo.reset(newFormData);

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
  const isPast =
    deadline?.status === "locked" || (timeRemaining?.isPast ?? false);
  const isReadOnly =
    preferenceData?.period_status === "past" || deadline?.status === "locked";

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-3 py-4 sm:px-4 sm:py-8">
        {/* Header */}
        <div className="mb-6 flex items-center space-x-3 sm:space-x-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/doctor")}
            title="Back"
          >
            <ArrowLeft className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Back</span>
          </Button>
          <h2 className="text-2xl sm:text-3xl font-bold">My Preferences</h2>
        </div>

        {/* Month Picker */}
        <Card className="mb-6">
          <CardContent className="py-4">
            <div className="flex items-center justify-center space-x-4">
              <Button variant="outline" size="sm" onClick={goToPrevMonth}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-lg sm:text-xl font-semibold min-w-[150px] sm:min-w-[200px] text-center">
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
              isPast ? "bg-red-50 border-red-200" : "bg-blue-50 border-blue-200"
            }`}
          >
            <CardContent className="py-4">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-0">
                <div className="flex items-start sm:items-center gap-2 sm:space-x-3">
                  <Clock
                    className={`h-5 w-5 flex-shrink-0 mt-0.5 sm:mt-0 ${
                      isPast ? "text-red-600" : "text-blue-600"
                    }`}
                  />
                  <div className="min-w-0">
                    <span
                      className={`font-semibold ${
                        isPast ? "text-red-700" : "text-blue-700"
                      }`}
                    >
                      Status: {deadline.status === "locked" ? "Locked" : "Open"}
                    </span>
                    {deadline.deadline && (
                      <span className="block sm:inline sm:ml-4 text-sm text-gray-600">
                        Deadline: {formatDate(deadline.deadline)}
                        {timeRemaining && !timeRemaining.isPast && (
                          <span className="sm:ml-2 block sm:inline text-sm">
                            ({timeRemaining.days} day
                            {timeRemaining.days !== 1 ? "s" : ""} remaining)
                          </span>
                        )}
                      </span>
                    )}
                    {!deadline.deadline && (
                      <span className="block sm:inline sm:ml-4 text-gray-500 italic text-sm">
                        No deadline set
                      </span>
                    )}
                  </div>
                </div>
                {preferenceData && (
                  <div
                    className={`self-start sm:self-auto px-3 py-1 rounded-full text-sm font-medium flex-shrink-0 ${
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
            <CardTitle className="flex items-center gap-2">
              Preferences for {MONTH_NAMES[month - 1]} {year}
              <InfoTooltip content="Click cells to set your availability. Click to cycle: Available (gray) → Preferred (green) → Unavailable (red). Each row shows on-site and on-call separately." />
              {draft.isRestoredFromDraft && (
                <span className="text-amber-600 text-sm font-normal">
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
                onPreviousVersion={handlePreviousVersion}
                onNextVersion={handleNextVersion}
                canPreviousVersion={preferenceData?.can_undo ?? false}
                canNextVersion={preferenceData?.can_redo ?? false}
                status={preferenceData.status}
                periodStatus={preferenceData.period_status}
                validationErrors={validationErrors}
                saveError={saveError}
                onClearSaveError={() => setSaveError(null)}
                isSaving={saveLoading}
              />
            ) : null}
          </CardContent>
        </Card>
      </main>
    </div>
  );
};
