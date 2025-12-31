// Shared types and helpers for preferences components

export type DayState = "can" | "cant" | "want";

export const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAY_NAMES_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Get number of days in a month
export const getDaysInMonth = (year: number, month: number): number => {
  return new Date(year, month, 0).getDate();
};

// Get first day of month (0 = Monday, 6 = Sunday)
export const getFirstDayOfMonth = (year: number, month: number): number => {
  const day = new Date(year, month - 1, 1).getDay();
  return day === 0 ? 6 : day - 1; // Convert to Monday = 0
};

// Get day state from arrays
export const getDayState = (
  day: number,
  unavailableDays: number[],
  preferredDays: number[]
): DayState => {
  if (unavailableDays.includes(day)) return "cant";
  if (preferredDays.includes(day)) return "want";
  return "can";
};

// Cycle day state: can -> want -> cant -> can
export const getNextDayState = (currentState: DayState): DayState => {
  switch (currentState) {
    case "can": return "want";
    case "want": return "cant";
    case "cant": return "can";
  }
};

// Get weekday state from arrays (weekday is 0-6, Monday=0)
export const getWeekdayState = (
  weekday: number,
  preferredWeekdays: number[],
  avoidWeekdays: number[]
): DayState => {
  if (avoidWeekdays.includes(weekday)) return "cant";
  if (preferredWeekdays.includes(weekday)) return "want";
  return "can";
};

// Format deadline date
export const formatDate = (dateStr: string | null): string => {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

// Calculate time remaining until deadline
export interface TimeRemaining {
  days: number;
  hours: number;
  minutes: number;
  total: number; // total milliseconds
  isPast: boolean;
}

export const getTimeRemaining = (deadline: string | null): TimeRemaining | null => {
  if (!deadline) return null;
  const now = new Date();
  const deadlineDate = new Date(deadline);
  const total = deadlineDate.getTime() - now.getTime();

  if (total <= 0) {
    return { days: 0, hours: 0, minutes: 0, total: 0, isPast: true };
  }

  const days = Math.floor(total / (1000 * 60 * 60 * 24));
  const hours = Math.floor((total % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  const minutes = Math.floor((total % (1000 * 60 * 60)) / (1000 * 60));

  return { days, hours, minutes, total, isPast: false };
};

// Get weeks in month for calendar rendering
export interface CalendarWeek {
  weekNumber: number;
  days: (number | null)[]; // null for empty cells
}

export const getWeeksInMonth = (year: number, month: number): CalendarWeek[] => {
  const daysInMonth = getDaysInMonth(year, month);
  const firstDayOffset = getFirstDayOfMonth(year, month);
  const weeks: CalendarWeek[] = [];

  let currentDay = 1;
  let weekNumber = 1;

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
  weeks.push({ weekNumber: weekNumber++, days: firstWeek });

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
    weeks.push({ weekNumber: weekNumber++, days: week });
  }

  return weeks;
};

// Check if a day is a weekend (Saturday=5, Sunday=6 in our 0-based system)
export const isWeekend = (dayOfWeek: number): boolean => {
  return dayOfWeek === 5 || dayOfWeek === 6;
};

// Get day of week for a specific date (0 = Monday)
export const getDayOfWeek = (year: number, month: number, day: number): number => {
  const date = new Date(year, month - 1, day);
  const jsDay = date.getDay(); // 0 = Sunday
  return jsDay === 0 ? 6 : jsDay - 1; // Convert to Monday = 0
};

// Vacation period type
export interface VacationPeriod {
  startDay: number;
  endDay: number;
}

// Check if a day is in any vacation period
export const isDayInVacation = (day: number, vacations: VacationPeriod[]): boolean => {
  return vacations.some(v => v.startDay > 0 && v.endDay > 0 && day >= v.startDay && day <= v.endDay);
};

// Get all days from all vacation periods as array
export const getVacationDays = (vacations: VacationPeriod[]): number[] => {
  const days: number[] = [];
  for (const vacation of vacations) {
    if (vacation.startDay <= 0 || vacation.endDay <= 0) continue;
    for (let d = vacation.startDay; d <= vacation.endDay; d++) {
      days.push(d);
    }
  }
  return [...new Set(days)].sort((a, b) => a - b);
};

// Derive all vacation periods from unavailable days arrays
// Vacation periods are consecutive ranges of days that are in BOTH arrays
export const deriveVacationFromDays = (
  unavailableOnsiteDays: number[],
  unavailableOncallDays: number[]
): VacationPeriod[] => {
  // Find days that are in both arrays (intersection)
  const commonDays = unavailableOnsiteDays
    .filter((d) => unavailableOncallDays.includes(d))
    .sort((a, b) => a - b);

  if (commonDays.length === 0) return [];

  // Find all consecutive ranges
  const ranges: VacationPeriod[] = [];
  let rangeStart = commonDays[0];
  let rangeEnd = commonDays[0];

  for (let i = 1; i < commonDays.length; i++) {
    if (commonDays[i] === rangeEnd + 1) {
      // Continue the range
      rangeEnd = commonDays[i];
    } else {
      // Save current range if it has at least 2 days (typical for vacation)
      if (rangeEnd - rangeStart >= 1) {
        ranges.push({ startDay: rangeStart, endDay: rangeEnd });
      }
      // Start new range
      rangeStart = commonDays[i];
      rangeEnd = commonDays[i];
    }
  }

  // Don't forget the last range
  if (rangeEnd - rangeStart >= 1) {
    ranges.push({ startDay: rangeStart, endDay: rangeEnd });
  }

  return ranges;
};

// Check if a specific day number in a month is a weekend
export const isDayWeekend = (year: number, month: number, day: number): boolean => {
  const dayOfWeek = getDayOfWeek(year, month, day);
  return isWeekend(dayOfWeek);
};

// Count weekday and weekend days in an array
export const countDaysByType = (
  year: number,
  month: number,
  days: number[]
): { weekdays: number; weekends: number } => {
  let weekdays = 0;
  let weekends = 0;
  for (const day of days) {
    if (isDayWeekend(year, month, day)) {
      weekends++;
    } else {
      weekdays++;
    }
  }
  return { weekdays, weekends };
};

// Count total weekdays and weekends in a month
export const getMonthDayCounts = (
  year: number,
  month: number
): { weekdays: number; weekends: number } => {
  const daysInMonth = getDaysInMonth(year, month);
  let weekdays = 0;
  let weekends = 0;
  for (let day = 1; day <= daysInMonth; day++) {
    if (isDayWeekend(year, month, day)) {
      weekends++;
    } else {
      weekdays++;
    }
  }
  return { weekdays, weekends };
};
