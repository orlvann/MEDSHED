import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import type { AvailabilityDayOverview, RiskLevel } from "../../../types";

interface AvailabilityHeatmapProps {
  year: number;
  month: number;
  days: AvailabilityDayOverview[];
  onDayClick: (day: number) => void;
  loading?: boolean;
  /** Days that had solver errors (shown as warning overlay even when availability is OK) */
  solverErrorDays?: Set<number>;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const getRiskColor = (risk: RiskLevel): string => {
  switch (risk) {
    case "ok":
      return "bg-green-50/70 hover:bg-green-100/70 border-green-200";
    case "alert":
      return "bg-yellow-50 hover:bg-yellow-100 border-yellow-200";
    case "critical":
      return "bg-red-50 hover:bg-red-100 border-red-200";
    default:
      return "bg-gray-50 hover:bg-gray-100 border-gray-200";
  }
};

const getRiskTextColor = (risk: RiskLevel): string => {
  switch (risk) {
    case "ok":
      return "text-green-800";
    case "alert":
      return "text-yellow-800";
    case "critical":
      return "text-red-800";
    default:
      return "text-gray-600";
  }
};

export const AvailabilityHeatmap = ({
  year,
  month,
  days,
  onDayClick,
  loading = false,
  solverErrorDays,
}: AvailabilityHeatmapProps) => {
  // Get number of days in month and first day of week (0 = Sunday, 1 = Monday, etc.)
  const daysInMonth = new Date(year, month, 0).getDate();
  const firstDayOfMonth = new Date(year, month - 1, 1).getDay();
  // Convert Sunday = 0 to Monday-based (0 = Monday, 6 = Sunday)
  const firstDayOffset = firstDayOfMonth === 0 ? 6 : firstDayOfMonth - 1;

  // Create array of day numbers with empty slots for offset
  const calendarDays: (number | null)[] = [];
  for (let i = 0; i < firstDayOffset; i++) {
    calendarDays.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    calendarDays.push(day);
  }

  // Create a map for quick day lookup
  const dayMap = new Map<number, AvailabilityDayOverview>();
  days.forEach((d) => dayMap.set(d.day, d));

  // Split into weeks
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < calendarDays.length; i += 7) {
    weeks.push(calendarDays.slice(i, i + 7));
  }
  // Pad last week if needed
  const lastWeek = weeks[weeks.length - 1];
  while (lastWeek && lastWeek.length < 7) {
    lastWeek.push(null);
  }

  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  return (
    <Card className="mb-4 sm:mb-6">
      <CardHeader className="px-4 py-3 sm:px-6 sm:py-6">
        <CardTitle className="text-base sm:text-lg font-semibold">
          Availability - {monthName} {year}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-2 sm:px-6 pb-4 sm:pb-6">
        {loading ? (
          <div className="text-center py-6 sm:py-8 text-xs sm:text-sm text-muted-foreground">
            Loading availability data...
          </div>
        ) : days.length === 0 ? (
          <div className="text-center py-6 sm:py-8 text-xs sm:text-sm text-muted-foreground">
            No availability data for this month.
          </div>
        ) : (
          <>
            {/* Legend */}
            <div className="flex gap-3 sm:gap-4 mb-3 sm:mb-4 text-xs sm:text-sm px-2 sm:px-0">
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 sm:w-4 sm:h-4 rounded bg-green-50/70 border border-green-200" />
                <span>OK</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 sm:w-4 sm:h-4 rounded bg-yellow-50 border border-yellow-200" />
                <span>Alert</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 sm:w-4 sm:h-4 rounded bg-red-50 border border-red-200" />
                <span>Critical</span>
              </div>
            </div>

            {/* Calendar grid */}
            <div className="border rounded-lg overflow-hidden">
              {/* Weekday headers */}
              <div className="grid grid-cols-7 bg-gray-50 border-b">
                {WEEKDAY_LABELS.map((label, idx) => (
                  <div
                    key={label}
                    className={`py-1.5 sm:py-2 text-center text-[10px] sm:text-sm font-medium text-gray-600 ${
                      idx >= 5 ? "bg-gray-100" : ""
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
                          className="min-h-[60px] sm:min-h-[100px] bg-gray-50 border-r last:border-r-0"
                        />
                      );
                    }

                    const dayData = dayMap.get(day);
                    const risk = dayData?.risk || "ok";
                    const isWeekend = dayIdx >= 5;
                    const hasSolverError = solverErrorDays?.has(day) ?? false;

                    // If solver found an error on this day, override the color
                    const effectiveRisk = hasSolverError && risk === "ok" ? "critical" as const : risk;

                    return (
                      <button
                        key={day}
                        onClick={() => onDayClick(day)}
                        className={`min-h-[60px] sm:min-h-[100px] p-1 sm:p-2.5 text-left border-r last:border-r-0 transition-colors cursor-pointer active:opacity-70 ${getRiskColor(
                          effectiveRisk,
                        )} ${isWeekend ? "bg-opacity-70" : ""} ${hasSolverError ? "ring-2 ring-inset ring-red-400" : ""}`}
                      >
                        <div className="flex items-center gap-0.5 sm:gap-1">
                          <span
                            className={`text-xs sm:text-lg font-bold ${getRiskTextColor(effectiveRisk)}`}
                          >
                            {day}
                          </span>
                          {hasSolverError && (
                            <span className="px-0.5 sm:px-1 py-0.5 text-[8px] sm:text-[10px] font-bold bg-red-200 text-red-800 rounded" title="Solver found issues on this day">
                              !
                            </span>
                          )}
                        </div>
                        {dayData && (
                          <div className="mt-0.5 sm:mt-2 space-y-0.5 sm:space-y-1.5">
                            <div className="flex items-center justify-between">
                              <span className="hidden sm:inline px-1.5 py-0.5 text-xs font-medium bg-teal-100 text-teal-700 rounded">
                                On-site
                              </span>
                              <span
                                className={`text-[10px] sm:text-sm font-semibold ${getRiskTextColor(risk)}`}
                              >
                                <span className="sm:hidden">
                                  {dayData.available_specialists_onsite +
                                    dayData.available_residents_onsite}
                                </span>
                                <span className="hidden sm:inline">
                                  {dayData.available_specialists_onsite +
                                    dayData.available_residents_onsite}
                                </span>
                              </span>
                            </div>
                            <div className="flex items-center justify-between">
                              <span className="hidden sm:inline px-1.5 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded">
                                On-call
                              </span>
                              <span
                                className={`text-[10px] sm:text-sm font-semibold ${getRiskTextColor(risk)}`}
                              >
                                {dayData.available_specialists_oncall +
                                  dayData.available_residents_oncall}
                              </span>
                            </div>
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};
