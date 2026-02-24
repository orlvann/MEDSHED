import { useState } from "react";
import { ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "../ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import type { Assignment, DoctorMini } from "../../types";
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

// Abbreviate day names for mobile
const WEEKDAY_MOBILE = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

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
  doctors: DoctorMini[];
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
  const [selectedDay, setSelectedDay] = useState<number | null>(null);

  // Generate years for picker (current year -5 to +5)
  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: 11 }, (_, i) => currentYear - 5 + i);

  const goToPrevMonth = () => {
    if (month === 1) {
      onMonthChange(year - 1, 12);
    } else {
      onMonthChange(year, month - 1);
    }
    setSelectedDay(null);
  };

  const goToNextMonth = () => {
    if (month === 12) {
      onMonthChange(year + 1, 1);
    } else {
      onMonthChange(year, month + 1);
    }
    setSelectedDay(null);
  };

  // Get assignments for a specific day (current month only)
  const getDayAssignments = (
    day: number,
    isCurrentMonth: boolean
  ): Assignment[] => {
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
        ? doctorNames.get(pairedDoctor.doctor_id) ||
          `Doctor #${pairedDoctor.doctor_id}`
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

  // Get first name from full name
  const getFirstName = (doctorId: number): string => {
    const fullName = doctorNames.get(doctorId);
    if (!fullName) return `#${doctorId}`;
    return fullName.split(" ")[0];
  };

  // Get selected day details for the detail panel
  const getSelectedDayDetails = () => {
    if (!selectedDay) return null;
    const allDayAssignments = assignments.filter((a) => a.day === selectedDay);
    if (viewMode === "my-schedule" && currentDoctorId) {
      const hasMyShift = allDayAssignments.some(
        (a) => a.doctor_id === currentDoctorId
      );
      // Show all assignments only if the current doctor has a shift
      return {
        day: selectedDay,
        assignments: hasMyShift ? allDayAssignments : [],
      };
    }
    return { day: selectedDay, assignments: allDayAssignments };
  };

  const selectedDetails = getSelectedDayDetails();

  return (
    <div>
      {/* Controls Row */}
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        {/* Month Navigation */}
        <div className="flex items-center gap-1.5 sm:gap-2">
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
              className="inline-flex items-center justify-center gap-1 h-8 px-2 border rounded-md text-xs font-medium hover:bg-gray-50"
            >
              <span className="sm:hidden">
                {MONTH_NAMES[month - 1].slice(0, 3)} {year}
              </span>
              <span className="hidden sm:inline">Select month</span>
              <ChevronDown className="h-3 w-3" />
            </button>
            {showPicker && (
              <>
                <div
                  className="fixed inset-0 z-40 bg-black/30"
                  onClick={() => setShowPicker(false)}
                />
                <div className="fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white border rounded-xl shadow-xl p-4 w-[300px] max-w-[calc(100vw-2rem)]">
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
              </>
            )}
          </div>
        </div>

        {/* Doctor Filter (Team view only) */}
        {viewMode === "team-schedule" && (
          <Select
            value={highlightedDoctorId?.toString() ?? "all"}
            onValueChange={(value) =>
              onHighlightChange(value === "all" ? null : Number(value))
            }
          >
            <SelectTrigger className="w-[140px] sm:w-[200px] h-8 sm:h-9 text-xs sm:text-sm">
              <SelectValue placeholder="Highlight" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All doctors</SelectItem>
              {doctors.map((d) => (
                <SelectItem key={d.id} value={d.id.toString()}>
                  {d.first_name} {d.last_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Calendar Title */}
      <h2 className="text-lg sm:text-xl font-bold mb-3 sm:mb-4">
        {MONTH_NAMES[month - 1]} {year}
      </h2>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center h-64 sm:h-96">
          <div className="animate-pulse text-gray-500">Loading schedule...</div>
        </div>
      )}

      {/* No Schedule State */}
      {!loading && !hasPublishedSchedule && (
        <div className="flex items-center justify-center h-48 sm:h-96 border-2 border-dashed rounded-lg">
          <div className="text-center text-gray-500 px-4">
            <p className="text-base sm:text-lg font-medium">
              No published schedule yet
            </p>
            <p className="text-xs sm:text-sm">
              The schedule for {MONTH_NAMES[month - 1]} {year} has not been
              published.
            </p>
          </div>
        </div>
      )}

      {/* Calendar Grid */}
      {!loading && hasPublishedSchedule && (
        <>
          <div className="border rounded-lg overflow-hidden">
            {/* Weekday headers */}
            <div className="grid grid-cols-7 bg-gray-50 border-b">
              {WEEKDAY_NAMES_SHORT.map((day, idx) => (
                <div
                  key={day}
                  className="text-center text-[10px] sm:text-sm font-medium text-gray-500 py-1.5 sm:py-3 uppercase"
                >
                  <span className="sm:hidden">{WEEKDAY_MOBILE[idx]}</span>
                  <span className="hidden sm:inline">{day}</span>
                </div>
              ))}
            </div>

            {/* Calendar weeks */}
            {weeks.map((week, weekIdx) => (
              <div
                key={weekIdx}
                className="grid grid-cols-7 border-b last:border-b-0"
              >
                {week.days.map((dayInfo, dayIdx) => {
                  const { day, isCurrentMonth } = dayInfo;
                  const dayAssignments = getDayAssignments(day, isCurrentMonth);
                  const todayClass = isToday(day, isCurrentMonth);
                  const isSelected = selectedDay === day && isCurrentMonth;

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
                      onClick={() => {
                        if (isCurrentMonth) {
                          setSelectedDay(
                            selectedDay === day ? null : day
                          );
                        }
                      }}
                      className={`min-h-[48px] sm:min-h-[100px] p-0.5 sm:p-2 border-r last:border-r-0 cursor-pointer transition-colors ${
                        !isCurrentMonth
                          ? "bg-gray-50"
                          : isSelected
                          ? "bg-blue-50 ring-1 ring-inset ring-blue-200"
                          : "bg-white hover:bg-gray-50"
                      }`}
                    >
                      {/* Day number */}
                      <div
                        className={`text-[11px] sm:text-sm font-medium mb-0.5 sm:mb-2 text-center sm:text-left ${
                          !isCurrentMonth ? "text-gray-400" : "text-gray-900"
                        } ${
                          todayClass
                            ? "sm:w-7 sm:h-7 flex items-center justify-center sm:rounded-full sm:bg-primary/15 text-primary font-bold"
                            : ""
                        }`}
                      >
                        {day}
                      </div>

                      {/* Assignments */}
                      {isCurrentMonth && (
                        <div className="space-y-0.5 sm:space-y-1">
                          {/* === MOBILE: compact indicators === */}
                          <div className="sm:hidden flex flex-col items-center gap-0.5">
                            {viewMode === "my-schedule" && myInfo && (
                              <div
                                className={`w-full rounded-sm py-0.5 text-center text-[9px] font-semibold leading-tight ${
                                  myInfo.shiftType === "onsite"
                                    ? "bg-teal-100 text-teal-700"
                                    : "bg-amber-100 text-amber-700"
                                }`}
                              >
                                {myInfo.shiftType === "onsite" ? "OS" : "OC"}
                              </div>
                            )}
                            {viewMode === "team-schedule" && (
                              <>
                                {onsiteAssignment && (
                                  <div
                                    className={`w-full rounded-sm py-0.5 text-center text-[8px] font-medium leading-tight bg-teal-100 text-teal-700 truncate px-0.5 ${
                                      highlightedDoctorId ===
                                      onsiteAssignment.doctor_id
                                        ? "relative z-10 ring-1 ring-violet-500"
                                        : ""
                                    }`}
                                  >
                                    {getFirstName(onsiteAssignment.doctor_id)}
                                  </div>
                                )}
                                {oncallAssignment && (
                                  <div
                                    className={`w-full rounded-sm py-0.5 text-center text-[8px] font-medium leading-tight bg-amber-100 text-amber-700 truncate px-0.5 ${
                                      highlightedDoctorId ===
                                      oncallAssignment.doctor_id
                                        ? "relative z-10 ring-1 ring-violet-500"
                                        : ""
                                    }`}
                                  >
                                    {getFirstName(oncallAssignment.doctor_id)}
                                  </div>
                                )}
                              </>
                            )}
                          </div>

                          {/* === DESKTOP: full content === */}
                          <div className="hidden sm:block">
                            {viewMode === "my-schedule" && myInfo && (
                              <div
                                className={`text-xs rounded p-1.5 ${
                                  myInfo.shiftType === "onsite"
                                    ? "bg-teal-50 text-teal-800"
                                    : "bg-amber-50 text-amber-800 border border-amber-200"
                                }`}
                              >
                                <div className="font-medium">
                                  {myInfo.shiftType === "onsite"
                                    ? "On Site"
                                    : "On Call"}
                                </div>
                                {myInfo.pairedDoctorName && (
                                  <div className="text-gray-600">
                                    {myInfo.pairedDoctorName}
                                  </div>
                                )}
                              </div>
                            )}

                            {viewMode === "team-schedule" && (
                              <>
                                {onsiteAssignment && (
                                  <div
                                    className={`text-xs rounded p-1.5 bg-teal-50 text-teal-800 ${
                                      highlightedDoctorId ===
                                      onsiteAssignment.doctor_id
                                        ? "relative z-10 ring-2 ring-violet-500"
                                        : ""
                                    }`}
                                  >
                                    <div className="font-medium">On Site</div>
                                    <div className="text-teal-600">
                                      {doctorNames.get(
                                        onsiteAssignment.doctor_id
                                      ) ||
                                        `Doctor #${onsiteAssignment.doctor_id}`}
                                    </div>
                                  </div>
                                )}
                                {oncallAssignment && (
                                  <div
                                    className={`text-xs rounded p-1.5 bg-amber-50 text-amber-800 border border-amber-200 ${
                                      highlightedDoctorId ===
                                      oncallAssignment.doctor_id
                                        ? "relative z-10 ring-2 ring-violet-500"
                                        : ""
                                    }`}
                                  >
                                    <div className="font-medium">On Call</div>
                                    <div className="text-amber-600">
                                      {doctorNames.get(
                                        oncallAssignment.doctor_id
                                      ) ||
                                        `Doctor #${oncallAssignment.doctor_id}`}
                                    </div>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          {/* Mobile: Selected Day Detail Panel */}
          {selectedDetails && (
            <div className="mt-3 p-3 bg-white border rounded-lg sm:hidden">
              <p className="text-sm font-semibold text-gray-900 mb-2">
                {selectedDetails.day} {MONTH_NAMES[month - 1]} {year}
              </p>
              {selectedDetails.assignments.length === 0 ? (
                <p className="text-xs text-gray-500">
                  {viewMode === "my-schedule"
                    ? "You have no shifts this day"
                    : "No shifts scheduled"}
                </p>
              ) : (
                <div className="space-y-2">
                  {selectedDetails.assignments.map((a, idx) => (
                    <div
                      key={idx}
                      className={`flex items-center gap-2 text-sm rounded-md px-2.5 py-1.5 ${
                        a.shift_type === "onsite"
                          ? "bg-teal-50 text-teal-800"
                          : "bg-amber-50 text-amber-800"
                      }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          a.shift_type === "onsite"
                            ? "bg-teal-500"
                            : "bg-amber-500"
                        }`}
                      />
                      <span className="font-medium">
                        {a.shift_type === "onsite" ? "On Site" : "On Call"}
                      </span>
                      <span className="text-gray-600">
                        {doctorNames.get(a.doctor_id) ||
                          `Doctor #${a.doctor_id}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
