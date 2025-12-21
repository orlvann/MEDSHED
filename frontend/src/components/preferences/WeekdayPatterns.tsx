import { Card, CardContent } from "../ui/card";
import { InfoTooltip } from "./InfoTooltip";
import { WEEKDAY_NAMES, getWeekdayState, type DayState } from "./types";

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
      // CAN -> WANT (preferred)
      onChange(
        [...preferredWeekdays, weekday].sort((a, b) => a - b),
        avoidWeekdays
      );
    } else if (currentState === "want") {
      // WANT -> CAN'T (avoid)
      onChange(
        preferredWeekdays.filter((d) => d !== weekday),
        [...avoidWeekdays, weekday].sort((a, b) => a - b)
      );
    } else {
      // CAN'T -> CAN (neutral)
      onChange(preferredWeekdays, avoidWeekdays.filter((d) => d !== weekday));
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

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Preferred days of the week</h3>
            <InfoTooltip
              content="Click to cycle: Available (gray) → Preferred (green) → Avoid (red)"
            />
          </div>

          {/* On-site */}
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">on-site</h4>
            <div className="flex flex-wrap gap-2">
              {WEEKDAY_NAMES.map((name, idx) => {
                const state = getWeekdayState(idx, preferredOnsiteWeekdays, avoidOnsiteWeekdays);
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() =>
                      cycleWeekdayState(
                        idx,
                        state,
                        preferredOnsiteWeekdays,
                        avoidOnsiteWeekdays,
                        onOnsiteWeekdayChange
                      )
                    }
                    disabled={disabled}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${getButtonStyle(
                      state
                    )} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
          </div>

          {/* On-call */}
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">on-call</h4>
            <div className="flex flex-wrap gap-2">
              {WEEKDAY_NAMES.map((name, idx) => {
                const state = getWeekdayState(idx, preferredOncallWeekdays, avoidOncallWeekdays);
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() =>
                      cycleWeekdayState(
                        idx,
                        state,
                        preferredOncallWeekdays,
                        avoidOncallWeekdays,
                        onOncallWeekdayChange
                      )
                    }
                    disabled={disabled}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${getButtonStyle(
                      state
                    )} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
