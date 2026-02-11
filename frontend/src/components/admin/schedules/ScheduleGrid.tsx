import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { DoctorSelectDropdown } from "./DoctorSelectDropdown";
import { DayEditSheet } from "./DayEditSheet";
import { Star } from "lucide-react";
import { useIsMobile } from "../../../hooks/useMediaQuery";
import type {
  Assignment,
  InputsSnapshotRead,
  ShiftType,
} from "../../../types";

interface ScheduleGridProps {
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

const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function getWeekday(year: number, month: number, day: number): number {
  // 0=Mon..6=Sun
  const jsDay = new Date(year, month - 1, day).getDay();
  return jsDay === 0 ? 6 : jsDay - 1;
}

function isWeekend(weekday: number): boolean {
  return weekday >= 5;
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
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider leading-none ${
        isSpecialist
          ? "bg-violet-100 text-violet-700"
          : "bg-teal-100 text-teal-700"
      }`}
    >
      {isSpecialist ? "Specialist" : "Resident"}
    </span>
  );
}

function HeadBadge() {
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 leading-none">
      <Star className="h-2.5 w-2.5 fill-amber-500 text-amber-500" />
      Head
    </span>
  );
}

export const ScheduleGrid = ({
  year,
  month,
  assignments,
  inputsSnapshot,
  participantDoctorIds,
  readOnly,
  onAssignmentChange,
}: ScheduleGridProps) => {
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

  const getDoctorName = useCallback(
    (doctorId: number | undefined): string => {
      if (!doctorId) return "—";
      const snap = doctors[doctorId];
      return snap ? snap.display_name : `Doctor #${doctorId}`;
    },
    [doctors]
  );

  const handleCellClick = (day: number, shiftType: ShiftType) => {
    if (readOnly) return;
    setEditingCell({ day, shiftType });
  };

  const handleSelect = (day: number, shiftType: ShiftType, doctorId: number) => {
    onAssignmentChange?.(day, shiftType, doctorId);
    setEditingCell(null);
  };

  const rows = [];
  for (let day = 1; day <= daysInMonth; day++) {
    const weekday = getWeekday(year, month, day);
    const weekend = isWeekend(weekday);
    const today = isToday(year, month, day);
    const onsiteDoctorId = assignmentMap.get(`${day}-onsite`);
    const oncallDoctorId = assignmentMap.get(`${day}-oncall`);
    const onsiteSnap = onsiteDoctorId ? doctors[onsiteDoctorId] : undefined;
    const oncallSnap = oncallDoctorId ? doctors[oncallDoctorId] : undefined;

    rows.push(
      <tr
        key={day}
        className={`transition-colors ${
          weekend ? "bg-amber-50/40" : ""
        } ${
          today
            ? "bg-blue-50/50 border-l-[3px] border-l-blue-500"
            : ""
        } hover:bg-gray-50/80`}
      >
        <td className="px-4 py-3 text-sm font-bold text-center whitespace-nowrap tabular-nums">
          <span
            className={`inline-flex items-center justify-center w-7 h-7 rounded-full ${
              today
                ? "bg-blue-600 text-white"
                : weekend
                  ? "text-amber-700"
                  : "text-gray-700"
            }`}
          >
            {day}
          </span>
        </td>
        <td
          className={`px-4 py-3 text-sm text-center whitespace-nowrap ${
            weekend ? "text-amber-600 font-semibold" : "text-muted-foreground"
          }`}
        >
          {WEEKDAY_NAMES[weekday]}
        </td>
        <td className="px-4 py-3 text-sm relative">
          <div
            className={`flex items-center gap-2 ${
              !readOnly ? "cursor-pointer hover:bg-teal-50 rounded-md px-2 py-1 -mx-2 -my-1 transition-colors" : ""
            }`}
            onClick={() => handleCellClick(day, "onsite")}
          >
            <span className="inline-block w-2 h-2 rounded-full bg-teal-500 flex-shrink-0" />
            <span className="font-medium text-gray-800">{getDoctorName(onsiteDoctorId)}</span>
            {onsiteSnap && (
              <span className="flex items-center gap-1">
                <RoleBadge role={onsiteSnap.role} />
                {onsiteSnap.is_head && <HeadBadge />}
              </span>
            )}
          </div>
          {editingCell?.day === day &&
            editingCell?.shiftType === "onsite" &&
            inputsSnapshot && (
              <DoctorSelectDropdown
                doctors={doctors}
                participantDoctorIds={participantDoctorIds}
                currentDoctorId={onsiteDoctorId || 0}
                onSelect={(id) => handleSelect(day, "onsite", id)}
                onClose={() => setEditingCell(null)}
              />
            )}
        </td>
        <td className="px-4 py-3 text-sm relative">
          <div
            className={`flex items-center gap-2 ${
              !readOnly ? "cursor-pointer hover:bg-amber-50 rounded-md px-2 py-1 -mx-2 -my-1 transition-colors" : ""
            }`}
            onClick={() => handleCellClick(day, "oncall")}
          >
            <span className="inline-block w-2 h-2 rounded-full bg-amber-500 flex-shrink-0" />
            <span className="font-medium text-gray-800">{getDoctorName(oncallDoctorId)}</span>
            {oncallSnap && (
              <span className="flex items-center gap-1">
                <RoleBadge role={oncallSnap.role} />
                {oncallSnap.is_head && <HeadBadge />}
              </span>
            )}
          </div>
          {editingCell?.day === day &&
            editingCell?.shiftType === "oncall" &&
            inputsSnapshot && (
              <DoctorSelectDropdown
                doctors={doctors}
                participantDoctorIds={participantDoctorIds}
                currentDoctorId={oncallDoctorId || 0}
                onSelect={(id) => handleSelect(day, "oncall", id)}
                onClose={() => setEditingCell(null)}
              />
            )}
        </td>
      </tr>
    );
  }

  if (isMobile) {
    // Mobile card view
    const mobileCards = [];
    for (let day = 1; day <= daysInMonth; day++) {
      const weekday = getWeekday(year, month, day);
      const weekend = isWeekend(weekday);
      const today = isToday(year, month, day);
      const onsiteDoctorId = assignmentMap.get(`${day}-onsite`);
      const oncallDoctorId = assignmentMap.get(`${day}-oncall`);
      const onsiteSnap = onsiteDoctorId ? doctors[onsiteDoctorId] : undefined;
      const oncallSnap = oncallDoctorId ? doctors[oncallDoctorId] : undefined;

      mobileCards.push(
        <div
          key={day}
          className={`border rounded-lg p-2.5 ${weekend ? "bg-amber-50/40" : ""} ${today ? "border-blue-500 border-l-[3px]" : ""} ${!readOnly ? "cursor-pointer active:bg-gray-100" : ""}`}
          onClick={() => { if (!readOnly) setSheetDay(day); }}
        >
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${today ? "bg-blue-600 text-white" : weekend ? "text-amber-700" : "text-gray-700"}`}>
              {day}
            </span>
            <span className={`text-xs ${weekend ? "text-amber-600 font-semibold" : "text-muted-foreground"}`}>
              {WEEKDAY_NAMES[weekday]}
            </span>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500 flex-shrink-0" />
              <span className="text-[10px] text-muted-foreground w-10">Onsite</span>
              <span className="font-medium text-gray-800 truncate">{getDoctorName(onsiteDoctorId)}</span>
              {onsiteSnap && <RoleBadge role={onsiteSnap.role} />}
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
              <span className="text-[10px] text-muted-foreground w-10">Oncall</span>
              <span className="font-medium text-gray-800 truncate">{getDoctorName(oncallDoctorId)}</span>
              {oncallSnap && <RoleBadge role={oncallSnap.role} />}
            </div>
          </div>
        </div>
      );
    }

    return (
      <Card className="mb-4 sm:mb-6">
        <CardHeader className="px-4 py-3">
          <CardTitle className="text-base">Schedule</CardTitle>
        </CardHeader>
        <CardContent className="px-3 pb-4">
          <div className="space-y-1.5">{mobileCards}</div>

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
  }

  return (
    <Card className="mb-4 sm:mb-6">
      <CardHeader className="px-4 py-3 sm:px-6 sm:py-6">
        <CardTitle className="text-base sm:text-lg">Schedule</CardTitle>
      </CardHeader>
      <CardContent className="px-4 sm:px-6">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50/80 border-b">
                <th className="px-4 py-2.5 text-xs font-semibold text-muted-foreground text-center w-14 uppercase tracking-wider">
                  Day
                </th>
                <th className="px-4 py-2.5 text-xs font-semibold text-muted-foreground text-center w-20 uppercase tracking-wider">
                  Weekday
                </th>
                <th className="px-4 py-2.5 text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full bg-teal-500" />
                    Onsite Doctor
                  </span>
                </th>
                <th className="px-4 py-2.5 text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                    Oncall Doctor
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">{rows}</tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
};
