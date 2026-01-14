import { useState, useCallback, useMemo } from "react";
import { Undo2, Redo2, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { Button } from "../ui/button";
import { IntegratedCalendar } from "./IntegratedCalendar";
import { StatusCountdown } from "./StatusCountdown";
import { ShiftCountsGrid } from "./ShiftCountsGrid";
import { WeekdayPatterns } from "./WeekdayPatterns";
import { ColleagueSelector } from "./ColleagueSelector";
import { AdditionalNote } from "./AdditionalNote";
import { WeekendRuleSection } from "./WeekendRuleSection";
import { VacationModal } from "./VacationModal";
import {
  getDayState,
  getNextDayState,
  getDaysInMonth,
  deriveVacationFromDays,
  type VacationPeriod,
} from "./types";
import type { ValidationError } from "./validation";
import type {
  Doctor,
  PreferenceWorkingPut,
  PreferenceStatus,
  PreferencesDeadlineRead,
  PeriodStatus,
} from "../../types";

export interface PreferencesEditorProps {
  // Mode for future doctor page support
  mode: "admin" | "doctor";

  // Data context
  doctorId: number;
  doctorName: string;
  year: number;
  month: number;

  // External data
  colleagues: Doctor[];
  deadline: PreferencesDeadlineRead | null;

  // Form data (controlled)
  formData: PreferenceWorkingPut;
  onFormDataChange: (data: PreferenceWorkingPut) => void;

  // Month navigation (optional, for integrated calendar)
  onMonthChange?: (year: number, month: number) => void;

  // Callbacks
  onSave: () => Promise<void>;

  // Local undo/redo (client-side history, sync)
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;

  // Server version browsing (async)
  onPreviousVersion?: () => Promise<void>;
  onNextVersion?: () => Promise<void>;
  canPreviousVersion?: boolean;
  canNextVersion?: boolean;

  // State from parent
  status: PreferenceStatus;
  periodStatus?: PeriodStatus;

  // Validation
  validationErrors?: ValidationError[];

  // Loading states
  isSaving?: boolean;
  isLoading?: boolean;
}

// Default empty preference form
export const getDefaultPreferences = (): PreferenceWorkingPut => ({
  unavailable_onsite_days: [],
  unavailable_oncall_days: [],
  preferred_onsite_days: [],
  preferred_oncall_days: [],
  min_onsite_total: 0,
  max_onsite_total: 0,
  target_onsite_total: 0,
  min_oncall_total: 0,
  max_oncall_total: 0,
  target_oncall_total: 0,
  max_onsite_weekends: 0,
  target_onsite_weekends: 0,
  max_oncall_weekends: 0,
  target_oncall_weekends: 0,
  preferred_onsite_weekdays: [],
  preferred_oncall_weekdays: [],
  avoid_onsite_weekdays: [],
  avoid_oncall_weekdays: [],
  allow_weekend_consecutive_onsite_oncall: false,
  preferred_partners: [],
  comments: null,
});

export const PreferencesEditor = ({
  mode,
  doctorId,
  doctorName: _doctorName,
  year,
  month,
  colleagues,
  deadline,
  formData,
  onFormDataChange,
  onMonthChange,
  onSave,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onPreviousVersion,
  onNextVersion,
  canPreviousVersion = false,
  canNextVersion = false,
  status,
  periodStatus,
  validationErrors = [],
  isSaving = false,
  isLoading = false,
}: PreferencesEditorProps) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [vacationModalOpen, setVacationModalOpen] = useState(false);

  // Derive vacations from formData so it's restored on undo/redo
  const vacations = useMemo(
    () =>
      deriveVacationFromDays(
        formData.unavailable_onsite_days,
        formData.unavailable_oncall_days
      ),
    [formData.unavailable_onsite_days, formData.unavailable_oncall_days]
  );

  // Derive read-only state from period status or deadline locked
  // For doctor mode: locked deadline = read-only
  // For admin mode: only past period = read-only (admin can edit after deadline)
  const isReadOnly =
    periodStatus === "past" ||
    (mode === "doctor" && deadline?.status === "locked");

  // Update a single field
  const updateField = useCallback(
    <K extends keyof PreferenceWorkingPut>(
      field: K,
      value: PreferenceWorkingPut[K]
    ) => {
      onFormDataChange({ ...formData, [field]: value });
    },
    [formData, onFormDataChange]
  );

  // Handle on-site day click (cycle state)
  const handleOnsiteDayClick = useCallback(
    (day: number) => {
      const currentState = getDayState(
        day,
        formData.unavailable_onsite_days,
        formData.preferred_onsite_days
      );
      const nextState = getNextDayState(currentState);

      let newUnavailable = formData.unavailable_onsite_days.filter(
        (d) => d !== day
      );
      let newPreferred = formData.preferred_onsite_days.filter(
        (d) => d !== day
      );

      if (nextState === "cant") {
        newUnavailable = [...newUnavailable, day].sort((a, b) => a - b);
      } else if (nextState === "want") {
        newPreferred = [...newPreferred, day].sort((a, b) => a - b);
      }

      onFormDataChange({
        ...formData,
        unavailable_onsite_days: newUnavailable,
        preferred_onsite_days: newPreferred,
      });
    },
    [formData, onFormDataChange]
  );

  // Handle on-call day click (cycle state)
  const handleOncallDayClick = useCallback(
    (day: number) => {
      const currentState = getDayState(
        day,
        formData.unavailable_oncall_days,
        formData.preferred_oncall_days
      );
      const nextState = getNextDayState(currentState);

      let newUnavailable = formData.unavailable_oncall_days.filter(
        (d) => d !== day
      );
      let newPreferred = formData.preferred_oncall_days.filter(
        (d) => d !== day
      );

      if (nextState === "cant") {
        newUnavailable = [...newUnavailable, day].sort((a, b) => a - b);
      } else if (nextState === "want") {
        newPreferred = [...newPreferred, day].sort((a, b) => a - b);
      }

      onFormDataChange({
        ...formData,
        unavailable_oncall_days: newUnavailable,
        preferred_oncall_days: newPreferred,
      });
    },
    [formData, onFormDataChange]
  );

  // Set all on-site days to can't
  const handleSetAllOnsiteOff = useCallback(() => {
    const daysInMonth = getDaysInMonth(year, month);
    const allDays = Array.from({ length: daysInMonth }, (_, i) => i + 1);
    onFormDataChange({
      ...formData,
      unavailable_onsite_days: allDays,
      preferred_onsite_days: [],
    });
  }, [year, month, formData, onFormDataChange]);

  // Set all on-call days to can't
  const handleSetAllOncallOff = useCallback(() => {
    const daysInMonth = getDaysInMonth(year, month);
    const allDays = Array.from({ length: daysInMonth }, (_, i) => i + 1);
    onFormDataChange({
      ...formData,
      unavailable_oncall_days: allDays,
      preferred_oncall_days: [],
    });
  }, [year, month, formData, onFormDataChange]);

  // Open vacation modal
  const handleMarkVacation = useCallback(() => {
    setVacationModalOpen(true);
  }, []);

  // Save vacation periods - applies vacation days to formData
  const handleSaveVacation = useCallback(
    (newVacations: VacationPeriod[]) => {
      setVacationModalOpen(false);

      // Generate all days from all vacation periods
      const vacationDays: number[] = [];
      for (const vacation of newVacations) {
        for (let day = vacation.startDay; day <= vacation.endDay; day++) {
          vacationDays.push(day);
        }
      }

      // Get current vacation days to compare
      const currentVacationDays = new Set<number>();
      for (const v of vacations) {
        for (let d = v.startDay; d <= v.endDay; d++) {
          currentVacationDays.add(d);
        }
      }

      // Days to add (new vacations)
      const daysToAdd = vacationDays.filter((d) => !currentVacationDays.has(d));
      // Days to remove (no longer in vacation)
      const daysToRemove = [...currentVacationDays].filter(
        (d) => !vacationDays.includes(d)
      );

      // Update unavailable arrays
      let newUnavailableOnsite = [...formData.unavailable_onsite_days];
      let newUnavailableOncall = [...formData.unavailable_oncall_days];

      // Add new vacation days
      newUnavailableOnsite = [
        ...new Set([...newUnavailableOnsite, ...daysToAdd]),
      ];
      newUnavailableOncall = [
        ...new Set([...newUnavailableOncall, ...daysToAdd]),
      ];

      // Remove days that are no longer vacation (from both arrays)
      newUnavailableOnsite = newUnavailableOnsite.filter(
        (d) => !daysToRemove.includes(d)
      );
      newUnavailableOncall = newUnavailableOncall.filter(
        (d) => !daysToRemove.includes(d)
      );

      // Sort
      newUnavailableOnsite.sort((a, b) => a - b);
      newUnavailableOncall.sort((a, b) => a - b);

      // Remove vacation days from preferred arrays
      const allVacationDays = new Set(vacationDays);
      const newPreferredOnsite = formData.preferred_onsite_days.filter(
        (d) => !allVacationDays.has(d)
      );
      const newPreferredOncall = formData.preferred_oncall_days.filter(
        (d) => !allVacationDays.has(d)
      );

      onFormDataChange({
        ...formData,
        unavailable_onsite_days: newUnavailableOnsite,
        unavailable_oncall_days: newUnavailableOncall,
        preferred_onsite_days: newPreferredOnsite,
        preferred_oncall_days: newPreferredOncall,
      });
    },
    [formData, onFormDataChange, vacations]
  );

  // Reset all preferences
  const handleResetAll = useCallback(() => {
    onFormDataChange(getDefaultPreferences());
  }, [onFormDataChange]);

  // Submit/Save handler
  const handleSave = useCallback(async () => {
    setIsSubmitting(true);
    try {
      await onSave();
    } finally {
      setIsSubmitting(false);
    }
  }, [onSave]);

  // Handle shift count field change
  const handleShiftCountChange = useCallback(
    (field: string, value: number | null) => {
      onFormDataChange({ ...formData, [field]: value });
    },
    [formData, onFormDataChange]
  );

  // Handle weekday pattern changes
  const handleOnsiteWeekdayChange = useCallback(
    (preferred: number[], avoid: number[]) => {
      onFormDataChange({
        ...formData,
        preferred_onsite_weekdays: preferred,
        avoid_onsite_weekdays: avoid,
      });
    },
    [formData, onFormDataChange]
  );

  const handleOncallWeekdayChange = useCallback(
    (preferred: number[], avoid: number[]) => {
      onFormDataChange({
        ...formData,
        preferred_oncall_weekdays: preferred,
        avoid_oncall_weekdays: avoid,
      });
    },
    [formData, onFormDataChange]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground">Loading preferences...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Control buttons (top) */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onUndo}
            disabled={!canUndo || isSaving || isReadOnly}
            title="Undo"
          >
            <Undo2 className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onRedo}
            disabled={!canRedo || isSaving || isReadOnly}
            title="Redo"
          >
            <Redo2 className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPreviousVersion}
              disabled={!canPreviousVersion || isSaving || !onPreviousVersion}
              title="Previous version"
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onNextVersion}
              disabled={!canNextVersion || isSaving || !onNextVersion}
              title="Next version"
            >
              Next
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={
              isSubmitting ||
              isSaving ||
              isReadOnly ||
              validationErrors.length > 0
            }
            title="Save"
          >
            <Save className="h-4 w-4 mr-1" />
            Save
          </Button>
        </div>
      </div>

      {/* Top section: Calendar + Status panel */}
      <div className="flex gap-6">
        {/* Calendar (left side) */}
        <div className="flex-1">
          <IntegratedCalendar
            year={year}
            month={month}
            onMonthChange={onMonthChange}
            showNavigation={!!onMonthChange}
            unavailableOnsiteDays={formData.unavailable_onsite_days}
            preferredOnsiteDays={formData.preferred_onsite_days}
            onOnsiteDayClick={handleOnsiteDayClick}
            unavailableOncallDays={formData.unavailable_oncall_days}
            preferredOncallDays={formData.preferred_oncall_days}
            onOncallDayClick={handleOncallDayClick}
            vacations={vacations}
            disabled={isReadOnly}
          />
        </div>

        {/* Status panel (right side) */}
        <div className="w-64 flex-shrink-0">
          <StatusCountdown
            status={status}
            deadline={deadline?.deadline ?? null}
            onSetAllOnsiteOff={handleSetAllOnsiteOff}
            onSetAllOncallOff={handleSetAllOncallOff}
            onResetAll={handleResetAll}
            onMarkVacation={handleMarkVacation}
            mode={mode}
            disabled={isReadOnly}
          />
        </div>
      </div>

      {/* Bottom sections in 2-column grid */}
      <div className="grid grid-cols-2 gap-6">
        {/* Left column */}
        <div className="space-y-6">
          <ShiftCountsGrid
            maxOnsiteTotal={formData.max_onsite_total}
            targetOnsiteTotal={formData.target_onsite_total}
            maxOnsiteWeekends={formData.max_onsite_weekends}
            targetOnsiteWeekends={formData.target_onsite_weekends}
            maxOncallTotal={formData.max_oncall_total}
            targetOncallTotal={formData.target_oncall_total}
            maxOncallWeekends={formData.max_oncall_weekends}
            targetOncallWeekends={formData.target_oncall_weekends}
            onChange={handleShiftCountChange}
            disabled={isReadOnly}
            errors={validationErrors}
          />

          <AdditionalNote
            value={formData.comments}
            onChange={(value) => updateField("comments", value)}
            disabled={isReadOnly}
          />
        </div>

        {/* Right column */}
        <div className="space-y-6">
          <WeekdayPatterns
            preferredOnsiteWeekdays={formData.preferred_onsite_weekdays}
            avoidOnsiteWeekdays={formData.avoid_onsite_weekdays}
            onOnsiteWeekdayChange={handleOnsiteWeekdayChange}
            preferredOncallWeekdays={formData.preferred_oncall_weekdays}
            avoidOncallWeekdays={formData.avoid_oncall_weekdays}
            onOncallWeekdayChange={handleOncallWeekdayChange}
            disabled={isReadOnly}
          />

          <ColleagueSelector
            colleagues={colleagues}
            selectedIds={formData.preferred_partners}
            currentDoctorId={doctorId}
            onChange={(ids) => updateField("preferred_partners", ids)}
            disabled={isReadOnly}
          />

          <WeekendRuleSection
            checked={formData.allow_weekend_consecutive_onsite_oncall}
            onChange={(checked) =>
              updateField("allow_weekend_consecutive_onsite_oncall", checked)
            }
            disabled={isReadOnly}
          />
        </div>
      </div>

      {/* Control buttons (bottom) */}
      <div className="flex items-center justify-between pt-4 border-t">
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onUndo}
            disabled={!canUndo || isSaving || isReadOnly}
            title="Undo"
          >
            <Undo2 className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onRedo}
            disabled={!canRedo || isSaving || isReadOnly}
            title="Redo"
          >
            <Redo2 className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPreviousVersion}
              disabled={!canPreviousVersion || isSaving || !onPreviousVersion}
              title="Previous version"
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onNextVersion}
              disabled={!canNextVersion || isSaving || !onNextVersion}
              title="Next version"
            >
              Next
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={
              isSubmitting ||
              isSaving ||
              isReadOnly ||
              validationErrors.length > 0
            }
            title="Save"
          >
            <Save className="h-4 w-4 mr-1" />
            {isSubmitting ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>

      {/* Vacation Modal */}
      <VacationModal
        isOpen={vacationModalOpen}
        onClose={() => setVacationModalOpen(false)}
        onSave={handleSaveVacation}
        year={year}
        month={month}
        existingVacations={vacations}
      />
    </div>
  );
};
