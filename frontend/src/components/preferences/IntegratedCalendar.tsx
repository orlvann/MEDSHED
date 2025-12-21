import { ChevronLeft, ChevronRight, Flag } from "lucide-react";
import { Button } from "../ui/button";
import {
  MONTH_NAMES,
  WEEKDAY_NAMES_SHORT,
  getWeeksInMonth,
  getDayState,
  isDayInVacation,
  type DayState,
  type VacationPeriod,
} from "./types";

interface IntegratedCalendarProps {
  year: number;
  month: number;
  onMonthChange?: (year: number, month: number) => void;
  showNavigation?: boolean;

  // On-site availability
  unavailableOnsiteDays: number[];
  preferredOnsiteDays: number[];
  onOnsiteDayClick: (day: number) => void;

  // On-call availability
  unavailableOncallDays: number[];
  preferredOncallDays: number[];
  onOncallDayClick: (day: number) => void;

  // Vacation
  vacation?: VacationPeriod | null;

  disabled?: boolean;
}

export const IntegratedCalendar = ({
  year,
  month,
  onMonthChange,
  showNavigation = true,
  unavailableOnsiteDays,
  preferredOnsiteDays,
  onOnsiteDayClick,
  unavailableOncallDays,
  preferredOncallDays,
  onOncallDayClick,
  vacation = null,
  disabled = false,
}: IntegratedCalendarProps) => {
  const weeks = getWeeksInMonth(year, month);

  const goToPrevMonth = () => {
    if (!onMonthChange) return;
    if (month === 1) {
      onMonthChange(year - 1, 12);
    } else {
      onMonthChange(year, month - 1);
    }
  };

  const goToNextMonth = () => {
    if (!onMonthChange) return;
    if (month === 12) {
      onMonthChange(year + 1, 1);
    } else {
      onMonthChange(year, month + 1);
    }
  };

  const getDayCellStyle = (state: DayState, isVacation: boolean) => {
    if (isVacation) {
      return "bg-purple-100 text-purple-700 border-purple-200";
    }
    switch (state) {
      case "want":
        return "bg-green-100 text-green-700 hover:bg-green-200 border-green-200";
      case "cant":
        return "bg-red-100 text-red-700 hover:bg-red-200 border-red-200";
      default:
        return "bg-gray-50 text-gray-700 hover:bg-gray-100 border-gray-200";
    }
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Month navigation header */}
      {showNavigation && (
        <div className="flex items-center justify-center py-3 border-b border-gray-200 bg-white">
          <Button
            variant="ghost"
            size="sm"
            onClick={goToPrevMonth}
            disabled={!onMonthChange}
            className="h-8 w-8 p-0"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="mx-4 text-lg font-semibold min-w-[160px] text-center">
            {MONTH_NAMES[month - 1]} {year}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={goToNextMonth}
            disabled={!onMonthChange}
            className="h-8 w-8 p-0"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Calendar grid */}
      <div className="bg-white">
        {/* Header row with weekday names */}
        <div className="grid grid-cols-8 border-b border-gray-200">
          <div className="p-2 text-center text-xs font-medium text-gray-500 border-r border-gray-200"></div>
          {WEEKDAY_NAMES_SHORT.map((day) => (
            <div
              key={day}
              className="p-2 text-center text-xs font-medium text-gray-500 uppercase"
            >
              {day}
            </div>
          ))}
        </div>

        {/* Weeks */}
        {weeks.map((week) => (
          <div key={week.weekNumber} className="border-b border-gray-200 last:border-b-0">
            {/* Day numbers row */}
            <div className="grid grid-cols-8 border-b border-gray-100">
              <div className="p-2 text-xs font-medium text-gray-400 border-r border-gray-200"></div>
              {week.days.map((day, dayIdx) => (
                <div
                  key={`day-${dayIdx}`}
                  className="p-1 text-center text-sm font-semibold text-gray-600 border-r border-gray-100 last:border-r-0"
                >
                  {day ?? ""}
                </div>
              ))}
            </div>

            {/* On-site row */}
            <div className="grid grid-cols-8">
              <div className="p-2 text-xs font-medium text-gray-600 border-r border-gray-200 flex items-center">
                on-site
              </div>
              {week.days.map((day, dayIdx) => {
                if (day === null) {
                  return (
                    <div
                      key={`empty-onsite-${dayIdx}`}
                      className="p-1 border-r border-gray-100 last:border-r-0 bg-gray-50/50 h-8"
                    />
                  );
                }
                const isVacation = isDayInVacation(day, vacation);
                const state = getDayState(day, unavailableOnsiteDays, preferredOnsiteDays);
                const isClickable = !disabled && !isVacation;

                return (
                  <button
                    key={`onsite-${day}`}
                    type="button"
                    onClick={() => isClickable && onOnsiteDayClick(day)}
                    disabled={!isClickable}
                    className={`p-1 h-8 text-sm font-medium border-r border-gray-100 last:border-r-0 transition-colors flex items-center justify-center ${getDayCellStyle(
                      state,
                      isVacation
                    )} ${!isClickable ? "cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    {isVacation && <Flag className="h-3 w-3" />}
                  </button>
                );
              })}
            </div>

            {/* On-call row */}
            <div className="grid grid-cols-8 border-t border-gray-100">
              <div className="p-2 text-xs font-medium text-gray-600 border-r border-gray-200 flex items-center">
                on-call
              </div>
              {week.days.map((day, dayIdx) => {
                if (day === null) {
                  return (
                    <div
                      key={`empty-oncall-${dayIdx}`}
                      className="p-1 border-r border-gray-100 last:border-r-0 bg-gray-50/50 h-8"
                    />
                  );
                }
                const isVacation = isDayInVacation(day, vacation);
                const state = getDayState(day, unavailableOncallDays, preferredOncallDays);
                const isClickable = !disabled && !isVacation;

                return (
                  <button
                    key={`oncall-${day}`}
                    type="button"
                    onClick={() => isClickable && onOncallDayClick(day)}
                    disabled={!isClickable}
                    className={`p-1 h-8 text-sm font-medium border-r border-gray-100 last:border-r-0 transition-colors flex items-center justify-center ${getDayCellStyle(
                      state,
                      isVacation
                    )} ${!isClickable ? "cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    {isVacation && <Flag className="h-3 w-3" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
