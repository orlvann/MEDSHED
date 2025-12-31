import { useState } from "react";
import { ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "../ui/button";
import type { Assignment, Doctor } from "../../types";
import {
  MONTH_NAMES,
  WEEKDAY_NAMES_SHORT,
  getDaysInMonth,
  getFirstDayOfMonth,
} from "../preferences/types";

type ScheduleViewMode = "my-schedule" | "team-schedule";

// Extended week type to include previous/next month days
interface CalendarDay {
  day: number;
  isCurrentMonth: boolean;
}

interface CalendarWeek {
  days: CalendarDay[];
}

// Get weeks with previous/next month days filled in
const getFullWeeksInMonth = (year: number, month: number): CalendarWeek[] => {
  const daysInMonth = getDaysInMonth(year, month);
  const firstDayOffset = getFirstDayOfMonth(year, month);
  const weeks: CalendarWeek[] = [];

  // Get previous month's days
  const prevMonth = month === 1 ? 12 : month - 1;
  const prevYear = month === 1 ? year - 1 : year;
  const daysInPrevMonth = getDaysInMonth(prevYear, prevMonth);

  let currentDay = 1;

  // First week with previous month days
  const firstWeek: CalendarDay[] = [];
  for (let i = 0; i < 7; i++) {
    if (i < firstDayOffset) {
      // Previous month day
      firstWeek.push({
        day: daysInPrevMonth - firstDayOffset + i + 1,
        isCurrentMonth: false,
      });
    } else if (currentDay <= daysInMonth) {
      firstWeek.push({ day: currentDay++, isCurrentMonth: true });
    }
  }
  weeks.push({ days: firstWeek });

  // Remaining weeks
  while (currentDay <= daysInMonth) {
    const week: CalendarDay[] = [];
    for (let i = 0; i < 7; i++) {
      if (currentDay <= daysInMonth) {
        week.push({ day: currentDay++, isCurrentMonth: true });
      } else {
        // Next month day
        week.push({
          day: currentDay - daysInMonth,
          isCurrentMonth: false,
        });
        currentDay++;
      }
    }
    weeks.push({ days: week });
  }

  return weeks;
};

interface FullScheduleCalendarProps {
  year: number;
  month: number;
  onMonthChange: (year: number, month: number) => void;
  assignments: Assignment[];
  viewMode: ScheduleViewMode;
  currentDoctorId: number | null;
  doctorNames: Map<number, string>;
  highlightedDoctorId: number | null;
  onHighlightChange: (doctorId: number | null) => void;
  doctors: Doctor[];
  loading?: boolean;
  hasPublishedSchedule: boolean;
}

export const FullScheduleCalendar = ({
  year,
  month,
  onMonthChange,
  assignments,
  viewMode,
  currentDoctorId,
  doctorNames,
  highlightedDoctorId,
  onHighlightChange,
  doctors,
  loading = false,
  hasPublishedSchedule,
}: FullScheduleCalendarProps) => {
  const weeks = getFullWeeksInMonth(year, month);
  const [showPicker, setShowPicker] = useState(false);

  // Generate years for picker (current year -5 to +5)
  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: 11 }, (_, i) => currentYear - 5 + i);

  const goToPrevMonth = () => {
    if (month === 1) {
      onMonthChange(year - 1, 12);
    } else {
      onMonthChange(year, month - 1);
    }
  };

  const goToNextMonth = () => {
    if (month === 12) {
      onMonthChange(year + 1, 1);
    } else {
      onMonthChange(year, month + 1);
    }
  };

  // Get assignments for a specific day (current month only)
  const getDayAssignments = (day: number, isCurrentMonth: boolean): Assignment[] => {
    if (!isCurrentMonth) return [];
    return assignments.filter((a) => a.day === day);
  };

  // For "My Schedule" view - get my shift and paired doctor info
  const getMyScheduleInfo = (day: number) => {
    const dayAssignments = assignments.filter((a) => a.day === day);
    const myShift = dayAssignments.find((a) => a.doctor_id === currentDoctorId);

    if (!myShift) return null;

    // Find paired doctor (other doctor on the same day)
    const pairedDoctor = dayAssignments.find(
      (a) => a.doctor_id !== currentDoctorId
    );

    return {
      shiftType: myShift.shift_type,
      pairedDoctorName: pairedDoctor
        ? doctorNames.get(pairedDoctor.doctor_id) || `Doctor #${pairedDoctor.doctor_id}`
        : null,
    };
  };

  // Check if today
  const isToday = (day: number, isCurrentMonth: boolean): boolean => {
    if (!isCurrentMonth) return false;
    const today = new Date();
    return (
      today.getFullYear() === year &&
      today.getMonth() + 1 === month &&
      today.getDate() === day
    );
  };

  return (
    <div>
      {/* Controls Row */}
      <div className="flex items-center justify-between mb-4">
        {/* Month Navigation */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={goToPrevMonth}
            className="h-8 w-8 p-0"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={goToNextMonth}
            className="h-8 w-8 p-0"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>

          {/* Month/Year Picker */}
          <div className="relative">
            <button
              onClick={() => setShowPicker(!showPicker)}
              className="flex items-center gap-2 px-3 py-1.5 border rounded-lg text-sm font-medium hover:bg-gray-50"
            >
              Select month
              <ChevronDown className="h-4 w-4" />
            </button>
            {showPicker && (
              <div className="absolute top-full left-0 mt-1 bg-white border rounded-lg shadow-lg z-20 p-3 min-w-[280px]">
                {/* Month selector */}
                <div className="grid grid-cols-3 gap-1 mb-3">
                  {MONTH_NAMES.map((m, idx) => (
                    <button
                      key={m}
                      onClick={() => {
                        onMonthChange(year, idx + 1);
                        setShowPicker(false);
                      }}
                      className={`px-2 py-1.5 text-sm rounded hover:bg-gray-100 ${
                        idx + 1 === month
                          ? "font-semibold bg-blue-100 text-blue-700"
                          : ""
                      }`}
                    >
                      {m.slice(0, 3)}
                    </button>
                  ))}
                </div>
                {/* Year selector */}
                <div className="border-t pt-2">
                  <div className="grid grid-cols-4 gap-1">
                    {years.map((y) => (
                      <button
                        key={y}
                        onClick={() => {
                          onMonthChange(y, month);
                          setShowPicker(false);
                        }}
                        className={`px-2 py-1.5 text-sm rounded hover:bg-gray-100 ${
                          y === year
                            ? "font-semibold bg-blue-100 text-blue-700"
                            : ""
                        }`}
                      >
                        {y}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right side controls */}
        <div className="flex items-center gap-4">
          {/* Doctor Filter (Team view only) */}
          {viewMode === "team-schedule" && (
            <div className="relative">
              <select
                value={highlightedDoctorId ?? ""}
                onChange={(e) =>
                  onHighlightChange(e.target.value ? Number(e.target.value) : null)
                }
                className="appearance-none border rounded-lg px-3 py-1.5 pr-8 text-sm bg-white cursor-pointer hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Highlight doctor</option>
                {doctors.map((d) => (
                  <option key={d.id} value={d.id}>
                    Dr. {d.first_name} {d.last_name}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500 pointer-events-none" />
            </div>
          )}

          {/* Legend */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 text-xs font-medium bg-gray-200 rounded">
                onDuty
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 text-xs font-medium border border-gray-400 rounded bg-white">
                onCall
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Calendar Title */}
      <h2 className="text-xl font-bold mb-4">
        {MONTH_NAMES[month - 1]} {year}
      </h2>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center h-96">
          <div className="animate-pulse text-gray-500">Loading schedule...</div>
        </div>
      )}

      {/* No Schedule State */}
      {!loading && !hasPublishedSchedule && (
        <div className="flex items-center justify-center h-96 border-2 border-dashed rounded-lg">
          <div className="text-center text-gray-500">
            <p className="text-lg font-medium">No published schedule yet</p>
            <p className="text-sm">
              The schedule for {MONTH_NAMES[month - 1]} {year} has not been
              published.
            </p>
          </div>
        </div>
      )}

      {/* Calendar Grid */}
      {!loading && hasPublishedSchedule && (
        <div className="border rounded-lg overflow-hidden">
          {/* Weekday headers */}
          <div className="grid grid-cols-7 bg-gray-50 border-b">
            {WEEKDAY_NAMES_SHORT.map((day) => (
              <div
                key={day}
                className="text-center text-sm font-medium text-gray-600 py-3 uppercase"
              >
                {day}
              </div>
            ))}
          </div>

          {/* Calendar weeks */}
          {weeks.map((week, weekIdx) => (
            <div key={weekIdx} className="grid grid-cols-7 border-b last:border-b-0">
              {week.days.map((dayInfo, dayIdx) => {
                const { day, isCurrentMonth } = dayInfo;
                const dayAssignments = getDayAssignments(day, isCurrentMonth);
                const todayClass = isToday(day, isCurrentMonth);

                // For My Schedule view
                const myInfo =
                  viewMode === "my-schedule" && isCurrentMonth
                    ? getMyScheduleInfo(day)
                    : null;

                // For Team Schedule view
                const onsiteAssignment =
                  viewMode === "team-schedule" && isCurrentMonth
                    ? dayAssignments.find((a) => a.shift_type === "onsite")
                    : null;
                const oncallAssignment =
                  viewMode === "team-schedule" && isCurrentMonth
                    ? dayAssignments.find((a) => a.shift_type === "oncall")
                    : null;

                return (
                  <div
                    key={`${weekIdx}-${dayIdx}`}
                    className={`min-h-[100px] p-2 border-r last:border-r-0 ${
                      !isCurrentMonth ? "bg-gray-50" : "bg-white"
                    }`}
                  >
                    {/* Day number */}
                    <div
                      className={`text-sm font-medium mb-2 ${
                        !isCurrentMonth ? "text-gray-400" : "text-gray-900"
                      } ${
                        todayClass
                          ? "w-7 h-7 flex items-center justify-center rounded-full bg-blue-500 text-white"
                          : ""
                      }`}
                    >
                      {day}
                    </div>

                    {/* Assignments */}
                    {isCurrentMonth && (
                      <div className="space-y-1">
                        {/* My Schedule View */}
                        {viewMode === "my-schedule" && myInfo && (
                          <div
                            className={`text-xs rounded p-1.5 ${
                              myInfo.shiftType === "onsite"
                                ? "bg-gray-200"
                                : "border border-gray-400 bg-white"
                            }`}
                          >
                            <div className="font-medium">
                              {myInfo.shiftType === "onsite" ? "onDuty" : "onCall"}
                            </div>
                            {myInfo.pairedDoctorName && (
                              <div className="text-gray-600">
                                w/ {myInfo.pairedDoctorName}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Team Schedule View */}
                        {viewMode === "team-schedule" && (
                          <>
                            {onsiteAssignment && (
                              <div
                                className={`text-xs rounded p-1.5 bg-gray-200 ${
                                  highlightedDoctorId === onsiteAssignment.doctor_id
                                    ? "ring-2 ring-blue-500"
                                    : ""
                                }`}
                              >
                                <div className="font-medium">onDuty</div>
                                <div className="text-gray-700">
                                  {doctorNames.get(onsiteAssignment.doctor_id) ||
                                    `Doctor #${onsiteAssignment.doctor_id}`}
                                </div>
                              </div>
                            )}
                            {oncallAssignment && (
                              <div
                                className={`text-xs rounded p-1.5 border border-gray-400 bg-white ${
                                  highlightedDoctorId === oncallAssignment.doctor_id
                                    ? "ring-2 ring-blue-500"
                                    : ""
                                }`}
                              >
                                <div className="font-medium">onCall</div>
                                <div className="text-gray-700">
                                  {doctorNames.get(oncallAssignment.doctor_id) ||
                                    `Doctor #${oncallAssignment.doctor_id}`}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
