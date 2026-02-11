import { InfoTooltip } from "./InfoTooltip";
import { WEEKDAY_NAMES, getWeekdayState, type DayState } from "./types";

const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface WeekdayPatternsProps {
  // On-site
  preferredOnsiteWeekdays: number[];
  avoidOnsiteWeekdays: number[];
  onOnsiteWeekdayChange: (preferred: number[], avoid: number[]) => void;

  // On-call
  preferredOncallWeekdays: number[];
  avoidOncallWeekdays: number[];
  onOncallWeekdayChange: (preferred: number[], avoid: number[]) => void;

  disabled?: boolean;
}

export const WeekdayPatterns = ({
  preferredOnsiteWeekdays,
  avoidOnsiteWeekdays,
  onOnsiteWeekdayChange,
  preferredOncallWeekdays,
  avoidOncallWeekdays,
  onOncallWeekdayChange,
  disabled = false,
}: WeekdayPatternsProps) => {
  const cycleWeekdayState = (
    weekday: number,
    currentState: DayState,
    preferredWeekdays: number[],
    avoidWeekdays: number[],
    onChange: (preferred: number[], avoid: number[]) => void
  ) => {
    if (currentState === "can") {
      onChange(
        [...preferredWeekdays, weekday].sort((a, b) => a - b),
        avoidWeekdays
      );
    } else if (currentState === "want") {
      onChange(
        preferredWeekdays.filter((d) => d !== weekday),
        [...avoidWeekdays, weekday].sort((a, b) => a - b)
      );
    } else {
      onChange(
        preferredWeekdays,
        avoidWeekdays.filter((d) => d !== weekday)
      );
    }
  };

  const getButtonStyle = (state: DayState) => {
    switch (state) {
      case "want":
        return "bg-green-100 text-green-700 border-green-300 hover:bg-green-200";
      case "cant":
        return "bg-red-100 text-red-700 border-red-300 hover:bg-red-200";
      default:
        return "bg-gray-100 text-gray-700 border-gray-300 hover:bg-gray-200";
    }
  };

  const renderRow = (
    label: string,
    preferredWeekdays: number[],
    avoidWeekdays: number[],
    onChange: (preferred: number[], avoid: number[]) => void
  ) => (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </h4>
      <div className="grid grid-cols-7 gap-1 sm:flex sm:flex-wrap sm:gap-2">
        {WEEKDAY_NAMES.map((name, idx) => {
          const state = getWeekdayState(idx, preferredWeekdays, avoidWeekdays);
          return (
            <button
              key={idx}
              type="button"
              onClick={() =>
                cycleWeekdayState(
                  idx,
                  state,
                  preferredWeekdays,
                  avoidWeekdays,
                  onChange
                )
              }
              disabled={disabled}
              className={`py-1.5 sm:px-3 sm:py-1.5 rounded-md text-xs sm:text-sm font-medium border transition-colors ${getButtonStyle(
                state
              )} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              <span className="sm:hidden">{WEEKDAY_SHORT[idx]}</span>
              <span className="hidden sm:inline">{name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="rounded-lg border border-gray-200 p-3 sm:p-4 space-y-3 sm:space-y-4 bg-white">
      <div className="flex items-center gap-2">
        <h3 className="text-sm sm:text-base font-semibold">
          Preferred days of the week
        </h3>
        <InfoTooltip content="Set your preferred weekday patterns. Click to cycle: Available (gray) → Preferred (green) → Avoid (red). This affects weekly recurring patterns, not specific dates." />
      </div>

      {renderRow(
        "on-site",
        preferredOnsiteWeekdays,
        avoidOnsiteWeekdays,
        onOnsiteWeekdayChange
      )}

      {renderRow(
        "on-call",
        preferredOncallWeekdays,
        avoidOncallWeekdays,
        onOncallWeekdayChange
      )}
    </div>
  );
};
