import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Button } from "../../ui/button";
import { X, AlertTriangle, Users, Pencil } from "lucide-react";
import { availabilityApi } from "../../../services/api";
import { getRiskIssueMessage } from "./riskMessages";
import { enrichIssueMessage, buildDoctorNameMap } from "./SolverErrorPanel";
import type {
  AvailabilityDayRead,
  Doctor,
  DoctorMini,
  RiskLevel,
} from "../../../types";

export interface SolverDayIssue {
  code: string;
  message: string;
}

interface DayDrilldownModalProps {
  year: number;
  month: number;
  day: number;
  onClose: () => void;
  /** Solver-reported issues for this day (from the error panel context) */
  solverIssues?: SolverDayIssue[];
  /** Full doctor list for resolving names in solver issues */
  doctors?: Doctor[];
}

const DoctorList = ({
  title,
  doctors,
}: {
  title: string;
  doctors: DoctorMini[];
}) => (
  <div className="bg-gray-50 rounded-lg p-2.5 sm:p-3">
    <h4 className="font-medium text-xs sm:text-sm text-gray-700 mb-1.5 sm:mb-2">{title}</h4>
    {doctors.length === 0 ? (
      <p className="text-xs sm:text-sm text-gray-400 italic">None</p>
    ) : (
      <ul className="space-y-0.5 sm:space-y-1">
        {doctors.map((doctor) => (
          <li key={doctor.id} className="text-xs sm:text-sm">
            {doctor.first_name} {doctor.last_name}
          </li>
        ))}
      </ul>
    )}
  </div>
);

const getRiskBadgeColor = (risk: RiskLevel): string => {
  switch (risk) {
    case "ok":
      return "bg-green-100 text-green-800";
    case "alert":
      return "bg-yellow-100 text-yellow-800";
    case "critical":
      return "bg-red-100 text-red-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
};

export const DayDrilldownModal = ({
  year,
  month,
  day,
  onClose,
  solverIssues,
  doctors,
}: DayDrilldownModalProps) => {
  const doctorNameMap = doctors ? buildDoctorNameMap(doctors) : new Map<number, string>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AvailabilityDayRead | null>(null);

  useEffect(() => {
    const fetchDayData = async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await availabilityApi.getDay(year, month, day);
        setData(result);
      } catch (err: any) {
        setError(err.response?.data?.detail || "Failed to load day details");
      } finally {
        setLoading(false);
      }
    };

    fetchDayData();
  }, [year, month, day]);

  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  const handleEditDoctors = () => {
    onClose();
    navigate("/admin/doctors");
  };

  const handleEditPreferences = () => {
    onClose();
    navigate(`/admin/preferences?year=${year}&month=${month}`);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-end sm:items-center justify-center z-50">
      <Card className="w-full max-w-2xl mx-0 sm:mx-4 rounded-t-lg sm:rounded-lg max-h-[90vh] overflow-y-auto">
        <CardHeader className="px-4 py-3 sm:px-6 sm:py-6 flex flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="text-base sm:text-xl">
              {monthName} {day}, {year}
            </CardTitle>
            {data && (() => {
              const hasSolverIssues = solverIssues && solverIssues.length > 0;
              const displayRisk = hasSolverIssues && data.risk === "ok" ? "critical" as const : data.risk;
              return (
                <span
                  className={`inline-block mt-1.5 sm:mt-2 px-1.5 sm:px-2 py-0.5 sm:py-1 text-[10px] sm:text-xs font-medium rounded ${getRiskBadgeColor(
                    displayRisk,
                  )}`}
                >
                  {displayRisk.toUpperCase()}
                </span>
              );
            })()}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
            <X className="h-4 w-4 sm:h-5 sm:w-5" />
          </Button>
        </CardHeader>
        <CardContent className="px-4 sm:px-6 pb-4 sm:pb-6">
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : error ? (
            <div className="text-center py-8 text-red-600">{error}</div>
          ) : data ? (
            <>
              {/* Solver Issues (from generate attempt) */}
              {solverIssues && solverIssues.length > 0 && (
                <div className="mb-3 sm:mb-4 p-2.5 sm:p-3 rounded-lg bg-red-50 border border-red-200">
                  <div className="flex items-center gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
                    <AlertTriangle className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-red-600" />
                    <span className="font-medium text-xs sm:text-sm text-red-800">
                      Solver issues
                    </span>
                  </div>
                  <ul className="space-y-0.5 sm:space-y-1">
                    {solverIssues.map((issue, idx) => (
                      <li key={idx} className="text-xs sm:text-sm text-red-700">
                        {enrichIssueMessage(issue.message, issue.code, doctorNameMap, year, month)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Risk Issues */}
              {data.risk !== "ok" && data.risk_issues.length > 0 && (
                <div
                  className={`mb-3 sm:mb-4 p-2.5 sm:p-3 rounded-lg ${
                    data.risk === "critical"
                      ? "bg-red-50 border border-red-200"
                      : "bg-yellow-50 border border-yellow-200"
                  }`}
                >
                  <div className="flex items-center gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
                    <AlertTriangle
                      className={`h-3.5 w-3.5 sm:h-4 sm:w-4 ${
                        data.risk === "critical"
                          ? "text-red-600"
                          : "text-yellow-600"
                      }`}
                    />
                    <span
                      className={`font-medium text-xs sm:text-sm ${
                        data.risk === "critical"
                          ? "text-red-800"
                          : "text-yellow-800"
                      }`}
                    >
                      {data.risk === "critical"
                        ? "Critical Coverage Issues"
                        : "Coverage Warnings"}
                    </span>
                  </div>
                  <ul className="space-y-0.5 sm:space-y-1">
                    {data.risk_issues.map((issue, idx) => (
                      <li
                        key={idx}
                        className={`text-xs sm:text-sm ${
                          data.risk === "critical"
                            ? "text-red-700"
                            : "text-yellow-700"
                        }`}
                      >
                        {getRiskIssueMessage(issue)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Suggested ignored slots for critical days */}
              {data.risk === "critical" &&
                data.suggested_ignored_slots.length > 0 && (
                  <div className="mb-3 sm:mb-4 p-2.5 sm:p-3 bg-gray-50 rounded-lg border border-gray-200">
                    <p className="text-xs sm:text-sm text-gray-700">
                      <strong>Gaps:</strong>{" "}
                      {data.suggested_ignored_slots
                        .map(
                          (slot) =>
                            `${slot.shift_type === "onsite" ? "On-site" : "On-call"}`,
                        )
                        .join(", ")}
                    </p>
                  </div>
                )}

              {/* Doctor Lists */}
              <div className="mb-3 sm:mb-4">
                <div className="flex items-center gap-1.5 sm:gap-2 mb-2 sm:mb-3">
                  <Users className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-gray-500" />
                  <h3 className="font-medium text-xs sm:text-sm text-gray-700">
                    Available Doctors
                  </h3>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:gap-3">
                  <DoctorList
                    title="Specialists (On-site)"
                    doctors={data.specialists_onsite}
                  />
                  <DoctorList
                    title="Residents (On-site)"
                    doctors={data.residents_onsite}
                  />
                  <DoctorList
                    title="Specialists (On-call)"
                    doctors={data.specialists_oncall}
                  />
                  <DoctorList
                    title="Residents (On-call)"
                    doctors={data.residents_oncall}
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 sm:gap-3 pt-3 sm:pt-4 border-t">
                <Button
                  variant="outline"
                  className="flex-1 h-8 text-xs sm:h-9 sm:text-sm"
                  onClick={handleEditDoctors}
                >
                  <Pencil className="h-3.5 w-3.5 sm:h-4 sm:w-4 mr-1.5 sm:mr-2" />
                  Edit Doctors
                </Button>
                <Button
                  variant="outline"
                  className="flex-1 h-8 text-xs sm:h-9 sm:text-sm"
                  onClick={handleEditPreferences}
                >
                  <Pencil className="h-3.5 w-3.5 sm:h-4 sm:w-4 mr-1.5 sm:mr-2" />
                  Edit Prefs
                </Button>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
};
