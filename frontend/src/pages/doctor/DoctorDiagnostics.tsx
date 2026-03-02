import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../../components/shared/Header";
import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Star,
  AlertTriangle,
  Calendar,
  Phone,
  ShieldCheck,
  Heart,
  Scale,
  Clock,
  Users,
  Sun,
} from "lucide-react";
import { schedulesApi } from "../../services/api";
import type { MyDoctorDiagnosticsRead, DoctorDiagnosticsRead } from "../../types";

/* ------------------------------------------------------------------ */
/*  SVG Radial Gauge                                                   */
/* ------------------------------------------------------------------ */

function RadialGauge({ stars, size = 160 }: { stars: number | null; size?: number }) {
  const maxStars = 5;
  const value = stars ?? 0;
  const fraction = value / maxStars;

  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - fraction);
  const center = size / 2;

  // Color based on rating
  const getColor = (v: number) => {
    if (v >= 4) return { stroke: "#10b981", bg: "#ecfdf5", text: "#065f46" }; // green
    if (v >= 3) return { stroke: "#f59e0b", bg: "#fffbeb", text: "#92400e" }; // amber
    if (v >= 2) return { stroke: "#f97316", bg: "#fff7ed", text: "#9a3412" }; // orange
    return { stroke: "#ef4444", bg: "#fef2f2", text: "#991b1b" }; // red
  };

  const colors = stars !== null ? getColor(value) : { stroke: "#d1d5db", bg: "#f9fafb", text: "#6b7280" };

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background track */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={strokeWidth}
        />
        {/* Value arc */}
        {stars !== null && (
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={colors.stroke}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className="transition-all duration-700 ease-out"
          />
        )}
      </svg>
      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {stars !== null ? (
          <>
            <span className="text-3xl font-bold tabular-nums" style={{ color: colors.text }}>
              {stars}
            </span>
            <span className="text-xs text-muted-foreground -mt-0.5">out of 5</span>
            <div className="flex items-center gap-0.5 mt-1.5">
              {Array.from({ length: 5 }, (_, i) => (
                <Star
                  key={i}
                  className={`h-3.5 w-3.5 ${
                    i < value ? "fill-yellow-400 text-yellow-400" : "text-gray-200"
                  }`}
                />
              ))}
            </div>
          </>
        ) : (
          <span className="text-sm text-muted-foreground">N/A</span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Category bar chart row                                             */
/* ------------------------------------------------------------------ */

interface CategoryBarProps {
  label: string;
  icon: React.ReactNode;
  stars: number | null;
  applicable: boolean;
}

const STAR_COLORS = [
  "", // 0 - unused
  "bg-red-500",
  "bg-orange-400",
  "bg-amber-400",
  "bg-lime-500",
  "bg-emerald-500",
];

const STAR_BG_COLORS = [
  "",
  "bg-red-100",
  "bg-orange-100",
  "bg-amber-100",
  "bg-lime-100",
  "bg-emerald-100",
];

function CategoryBar({ label, icon, stars, applicable }: CategoryBarProps) {
  if (!applicable) return null;

  const value = stars ?? 0;
  const pct = (value / 5) * 100;
  const barColor = STAR_COLORS[value] || "bg-gray-300";
  const bgColor = STAR_BG_COLORS[value] || "bg-gray-100";

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 w-28 sm:w-36 flex-shrink-0">
        <span className="text-muted-foreground flex-shrink-0">{icon}</span>
        <span className="text-xs sm:text-sm font-medium text-gray-700 truncate">
          {label}
        </span>
      </div>
      <div className="flex-1 flex items-center gap-2.5">
        <div className={`h-3 sm:h-3.5 flex-1 rounded-full overflow-hidden ${bgColor}`}>
          <div
            className={`h-full rounded-full transition-all duration-500 ease-out ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0 w-16 justify-end">
          {Array.from({ length: 5 }, (_, i) => (
            <Star
              key={i}
              className={`h-3 w-3 ${
                i < value ? "fill-yellow-400 text-yellow-400" : "text-gray-200"
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Stat card (compact KPI)                                            */
/* ------------------------------------------------------------------ */

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  bgClass: string;
  valueClass?: string;
}

function StatCard({ label, value, icon, bgClass, valueClass = "" }: StatCardProps) {
  return (
    <div className={`rounded-xl ${bgClass} p-3.5 sm:p-4`}>
      <div className="flex items-center gap-2 mb-1.5">
        {icon}
        <span className="text-[11px] sm:text-xs font-semibold uppercase tracking-wider opacity-70">
          {label}
        </span>
      </div>
      <p className={`text-xl sm:text-2xl font-bold tabular-nums ${valueClass}`}>
        {value}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Reason code badge labels                                           */
/* ------------------------------------------------------------------ */

const REASON_LABELS: Record<string, string> = {
  rest_violations: "Rest violations",
  preferences_not_fully_met: "Some preferences missed",
  unfair_distribution: "Uneven distribution",
  too_many_shifts: "High shift count",
  too_few_shifts: "Low shift count",
  weekend_heavy: "Weekend-heavy",
  perfect: "Everything looks great",
};

function reasonLabel(code: string): string {
  return REASON_LABELS[code] || code.replace(/_/g, " ");
}

/* ------------------------------------------------------------------ */
/*  Category icons + labels                                            */
/* ------------------------------------------------------------------ */

function getCategoryConfig(doc: DoctorDiagnosticsRead) {
  const c = doc.categories;
  return [
    { key: "rest", label: "Rest", icon: <Clock className="h-3.5 w-3.5" />, ...c.rest },
    { key: "fairness", label: "Fairness", icon: <Scale className="h-3.5 w-3.5" />, ...c.fairness },
    { key: "preferred_days", label: "Preferences", icon: <Heart className="h-3.5 w-3.5" />, ...c.preferred_days },
    { key: "totals", label: "Totals", icon: <Calendar className="h-3.5 w-3.5" />, ...c.totals },
    { key: "weekday_patterns", label: "Weekdays", icon: <Sun className="h-3.5 w-3.5" />, ...c.weekday_patterns },
    { key: "friday_free_weekend", label: "Weekends", icon: <ShieldCheck className="h-3.5 w-3.5" />, ...c.friday_free_weekend },
    { key: "preferred_partners", label: "Partners", icon: <Users className="h-3.5 w-3.5" />, ...c.preferred_partners },
  ];
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export const DoctorDiagnostics = () => {
  const navigate = useNavigate();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const [diagnostics, setDiagnostics] =
    useState<MyDoctorDiagnosticsRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDiagnostics = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await schedulesApi.getMyDiagnostics(year, month);
      setDiagnostics(data);
    } catch (err: any) {
      setDiagnostics(null);
      if (err.response?.status === 404) {
        setError("No published schedule found for this period.");
      } else if (err.response?.status === 403) {
        setError("You don't have permission to view diagnostics.");
      } else {
        setError("Failed to load diagnostics.");
      }
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    fetchDiagnostics();
  }, [fetchDiagnostics]);

  const handlePrevMonth = () => {
    if (month === 1) {
      setYear(year - 1);
      setMonth(12);
    } else {
      setMonth(month - 1);
    }
  };

  const handleNextMonth = () => {
    if (month === 12) {
      setYear(year + 1);
      setMonth(1);
    } else {
      setMonth(month + 1);
    }
  };

  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  const doc = diagnostics?.doctor;
  const categories = doc ? getCategoryConfig(doc) : [];
  const applicableCategories = categories.filter((c) => c.applicable);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="container mx-auto px-3 sm:px-4 py-4 sm:py-8 max-w-3xl">
        {/* Header */}
        <div className="mb-4 sm:mb-6 flex items-center space-x-3 sm:space-x-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/doctor")}
            title="Back"
          >
            <ArrowLeft className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Back</span>
          </Button>
          <h2 className="text-xl sm:text-3xl font-bold">My Diagnostics</h2>
        </div>

        {/* Month/Year Selector */}
        <Card className="mb-4 sm:mb-6">
          <CardContent className="py-3 sm:pt-6">
            <div className="flex items-center justify-center gap-3 sm:gap-4">
              <Button variant="outline" size="sm" onClick={handlePrevMonth}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="text-base sm:text-xl font-semibold min-w-[150px] sm:min-w-[180px] text-center">
                {monthName} {year}
              </div>
              <Button variant="outline" size="sm" onClick={handleNextMonth}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Loading */}
        {loading && (
          <div className="text-center py-16 text-sm text-muted-foreground">
            Loading diagnostics...
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <Card>
            <CardContent className="py-10 sm:py-14 text-center">
              <AlertTriangle className="h-10 w-10 text-gray-300 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Diagnostics content */}
        {!loading && !error && doc && (
          <div className="space-y-4 sm:space-y-5">
            {/* Top section: Gauge + KPIs */}
            <Card>
              <CardContent className="py-5 sm:py-6">
                <div className="flex flex-col sm:flex-row items-center gap-5 sm:gap-8">
                  {/* Radial gauge */}
                  <div className="flex flex-col items-center flex-shrink-0">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                      Overall Score
                    </p>
                    <RadialGauge stars={doc.ui_stars} size={150} />
                    {doc.ui_reasons_codes.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-3 justify-center max-w-[200px]">
                        {doc.ui_reasons_codes.map((code) => (
                          <span
                            key={code}
                            className="px-2 py-0.5 text-[10px] sm:text-xs bg-gray-100 text-gray-600 rounded-full"
                          >
                            {reasonLabel(code)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* KPI stats */}
                  <div className="flex-1 w-full grid grid-cols-2 gap-2.5 sm:gap-3">
                    <StatCard
                      label="On-site"
                      value={doc.assigned_onsite_total}
                      icon={<Calendar className="h-3.5 w-3.5 text-teal-600" />}
                      bgClass="bg-gradient-to-br from-teal-50 to-emerald-50 border border-teal-100/80"
                    />
                    <StatCard
                      label="On-call"
                      value={doc.assigned_oncall_total}
                      icon={<Phone className="h-3.5 w-3.5 text-amber-600" />}
                      bgClass="bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-100/80"
                    />
                    <StatCard
                      label="Rest Issues"
                      value={doc.rest_violations}
                      icon={
                        doc.rest_violations > 0 ? (
                          <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
                        ) : (
                          <ShieldCheck className="h-3.5 w-3.5 text-green-600" />
                        )
                      }
                      bgClass={
                        doc.rest_violations > 0
                          ? "bg-gradient-to-br from-red-50 to-rose-50 border border-red-100/80"
                          : "bg-gradient-to-br from-green-50 to-emerald-50 border border-green-100/80"
                      }
                      valueClass={doc.rest_violations > 0 ? "text-red-600" : "text-green-600"}
                    />
                    <StatCard
                      label="Prefs Met"
                      value={`${doc.preference_fulfillment_pct.toFixed(0)}%`}
                      icon={<Heart className="h-3.5 w-3.5 text-purple-600" />}
                      bgClass="bg-gradient-to-br from-purple-50 to-violet-50 border border-purple-100/80"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Category Breakdown */}
            {applicableCategories.length > 0 && (
              <Card>
                <CardContent className="py-5 sm:py-6">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">
                    Category Breakdown
                  </p>
                  <div className="space-y-3 sm:space-y-3.5">
                    {applicableCategories.map((cat) => (
                      <CategoryBar
                        key={cat.key}
                        label={cat.label}
                        icon={cat.icon}
                        stars={cat.stars}
                        applicable={cat.applicable}
                      />
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Preferred Days Detail */}
            {doc.preferred_days_requested > 0 && (
              <Card>
                <CardContent className="py-5 sm:py-6">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                    Preferred Days
                  </p>
                  <div className="flex items-end justify-between mb-2">
                    <div>
                      <span className="text-2xl font-bold tabular-nums">
                        {doc.preferred_days_requested - doc.preferred_days_missed}
                      </span>
                      <span className="text-sm text-muted-foreground ml-1">
                        of {doc.preferred_days_requested}
                      </span>
                    </div>
                    {doc.preferred_days_missed > 0 ? (
                      <span className="px-2.5 py-1 text-xs font-medium bg-amber-50 text-amber-700 rounded-full border border-amber-200">
                        {doc.preferred_days_missed} missed
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 text-xs font-medium bg-green-50 text-green-700 rounded-full border border-green-200">
                        All assigned
                      </span>
                    )}
                  </div>
                  {/* Segmented progress bar */}
                  <div className="flex gap-1">
                    {Array.from({ length: doc.preferred_days_requested }, (_, i) => {
                      const assigned = i < doc.preferred_days_requested - doc.preferred_days_missed;
                      return (
                        <div
                          key={i}
                          className={`h-3 flex-1 rounded-sm transition-all duration-300 ${
                            assigned ? "bg-purple-500" : "bg-gray-200"
                          }`}
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between mt-1.5">
                    <span className="text-[10px] text-muted-foreground">Assigned</span>
                    <span className="text-[10px] text-muted-foreground">Requested</span>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </main>
    </div>
  );
};
