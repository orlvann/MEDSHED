import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import type { Assignment, ShiftType } from "../../types";

// Calendar constants - Sunday start
const WEEKDAY_NAMES_SHORT = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

// Get number of days in a month
const getDaysInMonth = (year: number, month: number): number => {
  return new Date(year, month, 0).getDate();
};

// Get first day of month (0 = Sunday, 6 = Saturday) for Sunday-start calendar
const getFirstDayOfMonth = (year: number, month: number): number => {
  return new Date(year, month - 1, 1).getDay();
};

// Get weeks for calendar rendering (Sunday start)
interface CalendarWeek {
  days: (number | null)[];
}

const getWeeksInMonth = (year: number, month: number): CalendarWeek[] => {
  const daysInMonth = getDaysInMonth(year, month);
  const firstDayOffset = getFirstDayOfMonth(year, month);
  const weeks: CalendarWeek[] = [];

  let currentDay = 1;

  // First week with offset
  const firstWeek: (number | null)[] = [];
  for (let i = 0; i < 7; i++) {
    if (i < firstDayOffset) {
      firstWeek.push(null);
    } else if (currentDay <= daysInMonth) {
      firstWeek.push(currentDay++);
    } else {
      firstWeek.push(null);
    }
  }
  weeks.push({ days: firstWeek });

  // Remaining weeks
  while (currentDay <= daysInMonth) {
    const week: (number | null)[] = [];
    for (let i = 0; i < 7; i++) {
      if (currentDay <= daysInMonth) {
        week.push(currentDay++);
      } else {
        week.push(null);
      }
    }
    weeks.push({ days: week });
  }

  return weeks;
};

// Check if a day is today
const isToday = (year: number, month: number, day: number): boolean => {
  const today = new Date();
  return (
    today.getFullYear() === year &&
    today.getMonth() + 1 === month &&
    today.getDate() === day
  );
};

export interface DoctorInfo {
  id: number;
  name: string;
}

interface ScheduleCalendarProps {
  year: number;
  month: number;
  onMonthChange: (year: number, month: number) => void;
  assignments: Assignment[];
  selectedDate: number | null;
  onDateSelect: (day: number) => void;
  title: string;
  onViewAll?: () => void;
  doctorNames?: Map<number, string>;
  variant?: "personal" | "team";
}

export const ScheduleCalendar = ({
  year,
  month,
  onMonthChange,
  assignments,
  selectedDate,
  onDateSelect,
  title,
  onViewAll,
  doctorNames,
  variant = "personal",
}: ScheduleCalendarProps) => {
  const weeks = getWeeksInMonth(year, month);
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

  // Get assignments for a specific day
  const getDayAssignments = (day: number): Assignment[] => {
    return assignments.filter((a) => a.day === day);
  };

  // Get shift types for a day (for rendering circles)
  const getDayShiftTypes = (day: number): ShiftType[] => {
    const dayAssignments = getDayAssignments(day);
    const types = new Set<ShiftType>();
    dayAssignments.forEach((a) => types.add(a.shift_type));
    return Array.from(types);
  };

  // Get circle style based on shift type (personal mode)
  const getShiftCircleStyle = (shiftType: ShiftType): string => {
    if (shiftType === "onsite") {
      return "bg-teal-500 text-white";
    }
    return "bg-amber-400 text-white";
  };

  // Format selected date info
  const formatSelectedDateInfo = (): { date: string; events: { type: ShiftType; doctorName: string }[] } | null => {
    if (!selectedDate) return null;

    const dayAssignments = getDayAssignments(selectedDate);
    if (dayAssignments.length === 0) return null;

    const date = `${selectedDate} ${MONTH_NAMES[month - 1]} ${year}`;
    const events = dayAssignments.map((a) => ({
      type: a.shift_type,
      doctorName: doctorNames?.get(a.doctor_id) || `Doctor #${a.doctor_id}`,
    }));

    return { date, events };
  };

  const selectedInfo = formatSelectedDateInfo();

  return (
    <Card>
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">{title}</CardTitle>
          {onViewAll && (
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onViewAll}>
              View all
            </Button>
          )}
        </div>
        {/* Month navigation */}
        <div className="flex items-center gap-2 mt-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={goToPrevMonth}
            className="h-6 w-6 p-0 text-primary hover:bg-primary/10"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="relative">
            <button
              onClick={() => setShowPicker(!showPicker)}
              className="font-medium hover:underline text-sm text-primary"
            >
              {MONTH_NAMES[month - 1]} {year}
            </button>
            {showPicker && (
              <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1 bg-white border rounded-md shadow-lg z-10 p-2 min-w-[280px]">
                {/* Month selector */}
                <div className="grid grid-cols-3 gap-1 mb-2">
                  {MONTH_NAMES.map((m, idx) => (
                    <button
                      key={m}
                      onClick={() => {
                        onMonthChange(year, idx + 1);
                        setShowPicker(false);
                      }}
                      className={`px-2 py-1.5 text-xs rounded hover:bg-gray-100 ${
                        idx + 1 === month ? "font-semibold bg-blue-100 text-blue-700" : ""
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
                        className={`px-2 py-1.5 text-xs rounded hover:bg-gray-100 ${
                          y === year ? "font-semibold bg-blue-100 text-blue-700" : ""
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
          <Button
            variant="ghost"
            size="sm"
            onClick={goToNextMonth}
            className="h-6 w-6 p-0 text-primary hover:bg-primary/10"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0 px-4 pb-3">
        {/* Calendar grid */}
        <div className="w-full">
          {/* Weekday headers */}
          <div className="grid grid-cols-7">
            {WEEKDAY_NAMES_SHORT.map((day) => (
              <div
                key={day}
                className="text-center text-[10px] font-medium text-gray-400 py-1"
              >
                {day}
              </div>
            ))}
          </div>

          {/* Calendar days */}
          {weeks.map((week, weekIdx) => (
            <div key={weekIdx} className="grid grid-cols-7">
              {week.days.map((day, dayIdx) => {
                if (day === null) {
                  return <div key={`empty-${dayIdx}`} className="p-0.5 h-9" />;
                }

                const shiftTypes = getDayShiftTypes(day);
                const hasShifts = shiftTypes.length > 0;
                const isTodayDate = isToday(year, month, day);
                const isSelected = selectedDate === day;

                return (
                  <button
                    key={day}
                    onClick={() => onDateSelect(day)}
                    className={`p-0.5 h-9 flex items-center justify-center relative ${
                      isSelected ? "bg-gray-50 rounded" : ""
                    }`}
                  >
                    {variant === "team" ? (
                      // Team mode: plain number with small indicator dots below
                      <div className="flex flex-col items-center justify-center">
                        <span
                          className={`w-6 h-6 flex items-center justify-center text-xs leading-none ${
                            isTodayDate
                              ? "rounded-full bg-primary/15 text-primary font-bold"
                              : "text-gray-700"
                          }`}
                        >
                          {day}
                        </span>
                        {hasShifts ? (
                          <div className="flex items-center gap-1 mt-px">
                            {shiftTypes.includes("onsite") && (
                              <span className="w-1.5 h-1.5 rounded-full bg-teal-500" />
                            )}
                            {shiftTypes.includes("oncall") && (
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            )}
                          </div>
                        ) : (
                          <div className="h-1.5 mt-px" />
                        )}
                      </div>
                    ) : hasShifts ? (
                      // Personal mode: colored circle with day number
                      <div className="relative">
                        {shiftTypes.length === 1 ? (
                          <span
                            className={`w-8 h-8 rounded-full flex items-center justify-center text-base font-medium ${getShiftCircleStyle(
                              shiftTypes[0]
                            )}`}
                          >
                            {day}
                          </span>
                        ) : (
                          <div className="relative w-8 h-8">
                            <span
                              className={`absolute inset-0 w-8 h-8 rounded-full flex items-center justify-center text-base font-medium ${getShiftCircleStyle(
                                "onsite"
                              )}`}
                            >
                              {day}
                            </span>
                            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-amber-400 border border-white" />
                          </div>
                        )}
                      </div>
                    ) : (
                      // No shifts - plain day number
                      <span
                        className={`w-8 h-8 flex items-center justify-center text-base ${
                          isTodayDate
                            ? "rounded-full bg-primary/15 text-primary font-bold"
                            : "text-gray-700"
                        }`}
                      >
                        {day}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Selected date info */}
        {selectedInfo && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <p className="text-sm font-medium text-gray-900">
              {selectedInfo.date}
            </p>
            {selectedInfo.events.map((event, idx) => (
              <div key={idx} className="flex items-center gap-1.5 text-sm text-gray-600">
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    event.type === "onsite" ? "bg-teal-500" : "bg-amber-500"
                  }`}
                />
                <span>
                  {event.type === "onsite" ? "On Site" : "On Call"} — {event.doctorName}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Empty state for selected date with no events */}
        {selectedDate && !selectedInfo && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <p className="text-sm text-gray-700">
              No shifts scheduled for {selectedDate} {MONTH_NAMES[month - 1]} {year}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
