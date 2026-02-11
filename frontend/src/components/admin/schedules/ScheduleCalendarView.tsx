import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { DoctorSelectDropdown } from "./DoctorSelectDropdown";
import { DayEditSheet } from "./DayEditSheet";
import { useIsMobile } from "../../../hooks/useMediaQuery";
import type {
  Assignment,
  InputsSnapshotRead,
  ShiftType,
  DoctorSnapshotRead,
} from "../../../types";

interface ScheduleCalendarViewProps {
  year: number;
  month: number;
  assignments: Assignment[];
  inputsSnapshot: InputsSnapshotRead | null;
  participantDoctorIds: number[];
  readOnly: boolean;
  onAssignmentChange?: (
    day: number,
    shiftType: ShiftType,
    newDoctorId: number
  ) => void;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function isToday(year: number, month: number, day: number): boolean {
  const now = new Date();
  return (
    now.getFullYear() === year &&
    now.getMonth() + 1 === month &&
    now.getDate() === day
  );
}

function RoleBadge({ role }: { role: string }) {
  const isSpecialist = role === "specialist";
  return (
    <span
      className={`inline-flex items-center px-1 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider leading-none ${
        isSpecialist
          ? "bg-violet-100 text-violet-700"
          : "bg-teal-100 text-teal-700"
      }`}
    >
      {isSpecialist ? "SP" : "RE"}
    </span>
  );
}

function AssignmentChip({
  shiftType,
  doctor,
  isEditable,
  onClick,
}: {
  shiftType: ShiftType;
  doctor: DoctorSnapshotRead | undefined;
  isEditable: boolean;
  onClick?: () => void;
}) {
  const isOnsite = shiftType === "onsite";
  const dotColor = isOnsite ? "bg-teal-500" : "bg-amber-500";
  const hoverClass = isEditable
    ? isOnsite
      ? "hover:bg-teal-50 cursor-pointer"
      : "hover:bg-amber-50 cursor-pointer"
    : "";

  if (!doctor) {
    return (
      <button
        type="button"
        className={`flex items-center gap-1.5 px-1.5 py-1 rounded text-xs text-gray-400 w-full ${hoverClass}`}
        onClick={onClick}
        disabled={!isEditable}
      >
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full ${dotColor} opacity-40 flex-shrink-0`}
        />
        <span className="truncate">Unassigned</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      className={`flex items-center gap-1.5 px-1.5 py-1 rounded text-xs w-full transition-colors ${hoverClass}`}
      onClick={onClick}
      disabled={!isEditable}
    >
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${dotColor} flex-shrink-0`}
      />
      <span className="truncate font-medium text-gray-800">
        {doctor.display_name}
      </span>
      <RoleBadge role={doctor.role} />
    </button>
  );
}

export const ScheduleCalendarView = ({
  year,
  month,
  assignments,
  inputsSnapshot,
  participantDoctorIds,
  readOnly,
  onAssignmentChange,
}: ScheduleCalendarViewProps) => {
  const isMobile = useIsMobile();
  const [editingCell, setEditingCell] = useState<{
    day: number;
    shiftType: ShiftType;
  } | null>(null);
  const [sheetDay, setSheetDay] = useState<number | null>(null);

  const daysInMonth = getDaysInMonth(year, month);
  const doctors = inputsSnapshot?.doctors || {};

  // Build lookup: day -> shift_type -> doctor_id
  const assignmentMap = new Map<string, number>();
  for (const a of assignments) {
    assignmentMap.set(`${a.day}-${a.shift_type}`, a.doctor_id);
  }

  const getDoctor = useCallback(
    (doctorId: number | undefined): DoctorSnapshotRead | undefined => {
      if (!doctorId) return undefined;
      return doctors[doctorId];
    },
    [doctors]
  );

  const handleChipClick = (day: number, shiftType: ShiftType) => {
    if (readOnly) return;
    if (isMobile) {
      setSheetDay(day);
    } else {
      setEditingCell({ day, shiftType });
    }
  };

  const handleSelect = (
    day: number,
    shiftType: ShiftType,
    doctorId: number
  ) => {
    onAssignmentChange?.(day, shiftType, doctorId);
    setEditingCell(null);
  };

  // Calculate calendar layout
  const firstDayOfMonth = new Date(year, month - 1, 1).getDay();
  const firstDayOffset = firstDayOfMonth === 0 ? 6 : firstDayOfMonth - 1;

  const calendarDays: (number | null)[] = [];
  for (let i = 0; i < firstDayOffset; i++) {
    calendarDays.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    calendarDays.push(day);
  }

  // Split into weeks
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < calendarDays.length; i += 7) {
    weeks.push(calendarDays.slice(i, i + 7));
  }
  // Pad last week
  const lastWeek = weeks[weeks.length - 1];
  while (lastWeek && lastWeek.length < 7) {
    lastWeek.push(null);
  }

  return (
    <Card className="mb-4 sm:mb-6">
      <CardHeader className="px-3 py-3 sm:px-6 sm:pb-3">
        <CardTitle className="text-base sm:text-lg">Schedule</CardTitle>
      </CardHeader>
      <CardContent className="px-2 sm:px-6 pb-4 sm:pb-6">
        <div className="border rounded-xl bg-white overflow-hidden">
          {/* Weekday headers */}
          <div className="grid grid-cols-7 border-b">
            {WEEKDAY_LABELS.map((label, idx) => (
              <div
                key={label}
                className={`py-1.5 sm:py-2.5 text-center text-[10px] sm:text-xs font-semibold uppercase tracking-wider ${
                  idx >= 5
                    ? "bg-amber-50/60 text-amber-700"
                    : "bg-gray-50 text-gray-500"
                }`}
              >
                <span className="sm:hidden">{label.charAt(0)}</span>
                <span className="hidden sm:inline">{label}</span>
              </div>
            ))}
          </div>

          {/* Calendar weeks */}
          {weeks.map((week, weekIdx) => (
            <div
              key={weekIdx}
              className="grid grid-cols-7 border-b last:border-b-0"
            >
              {week.map((day, dayIdx) => {
                if (day === null) {
                  return (
                    <div
                      key={`empty-${weekIdx}-${dayIdx}`}
                      className={`min-h-[70px] sm:min-h-[110px] border-r last:border-r-0 ${
                        dayIdx >= 5 ? "bg-amber-50/30" : "bg-gray-50/50"
                      }`}
                    />
                  );
                }

                const isWeekend = dayIdx >= 5;
                const today = isToday(year, month, day);
                const onsiteDoctorId = assignmentMap.get(`${day}-onsite`);
                const oncallDoctorId = assignmentMap.get(`${day}-oncall`);
                const onsiteDoctor = getDoctor(onsiteDoctorId);
                const oncallDoctor = getDoctor(oncallDoctorId);

                return (
                  <div
                    key={day}
                    className={`min-h-[70px] sm:min-h-[110px] border-r last:border-r-0 p-0.5 sm:p-1.5 relative transition-colors overflow-hidden ${
                      isWeekend ? "bg-amber-50/30" : "bg-white"
                    }`}
                  >
                    {/* Day number */}
                    <div className="flex items-center justify-between mb-0.5 sm:mb-1.5">
                      <span
                        className={`inline-flex items-center justify-center w-5 h-5 sm:w-6 sm:h-6 rounded-full text-[10px] sm:text-xs font-bold ${
                          today
                            ? "bg-blue-600 text-white"
                            : isWeekend
                              ? "text-amber-700"
                              : "text-gray-700"
                        }`}
                      >
                        {day}
                      </span>
                    </div>

                    {/* Assignment chips */}
                    <div className="space-y-0 sm:space-y-0.5">
                      <div className="relative">
                        <AssignmentChip
                          shiftType="onsite"
                          doctor={onsiteDoctor}
                          isEditable={!readOnly}
                          onClick={() => handleChipClick(day, "onsite")}
                        />
                        {!isMobile &&
                          editingCell?.day === day &&
                          editingCell?.shiftType === "onsite" &&
                          inputsSnapshot && (
                            <DoctorSelectDropdown
                              doctors={doctors}
                              participantDoctorIds={participantDoctorIds}
                              currentDoctorId={onsiteDoctorId || 0}
                              onSelect={(id) =>
                                handleSelect(day, "onsite", id)
                              }
                              onClose={() => setEditingCell(null)}
                            />
                          )}
                      </div>
                      <div className="relative">
                        <AssignmentChip
                          shiftType="oncall"
                          doctor={oncallDoctor}
                          isEditable={!readOnly}
                          onClick={() => handleChipClick(day, "oncall")}
                        />
                        {!isMobile &&
                          editingCell?.day === day &&
                          editingCell?.shiftType === "oncall" &&
                          inputsSnapshot && (
                            <DoctorSelectDropdown
                              doctors={doctors}
                              participantDoctorIds={participantDoctorIds}
                              currentDoctorId={oncallDoctorId || 0}
                              onSelect={(id) =>
                                handleSelect(day, "oncall", id)
                              }
                              onClose={() => setEditingCell(null)}
                            />
                          )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 sm:gap-4 mt-2 sm:mt-3 text-[10px] sm:text-xs text-gray-500 px-1 sm:px-0">
          <div className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
            <span>Onsite</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500" />
            <span>Oncall</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 sm:w-3 sm:h-3 rounded bg-amber-50 border border-amber-200" />
            <span>Weekend</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 sm:w-3 sm:h-3 rounded-full bg-blue-600" />
            <span>Today</span>
          </div>
        </div>

        {sheetDay !== null && (
          <DayEditSheet
            open
            onOpenChange={(open) => { if (!open) setSheetDay(null); }}
            year={year}
            month={month}
            day={sheetDay}
            doctors={doctors}
            participantDoctorIds={participantDoctorIds}
            onsiteDoctorId={assignmentMap.get(`${sheetDay}-onsite`)}
            oncallDoctorId={assignmentMap.get(`${sheetDay}-oncall`)}
            readOnly={readOnly}
            onAssignmentChange={onAssignmentChange}
          />
        )}
      </CardContent>
    </Card>
  );
};
