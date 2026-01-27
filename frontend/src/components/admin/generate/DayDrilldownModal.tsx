import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Button } from "../../ui/button";
import { X, AlertTriangle, Users, Pencil } from "lucide-react";
import { availabilityApi } from "../../../services/api";
import { getRiskIssueMessage } from "./riskMessages";
import type {
  AvailabilityDayRead,
  DoctorMini,
  RiskLevel,
} from "../../../types";

interface DayDrilldownModalProps {
  year: number;
  month: number;
  day: number;
  onClose: () => void;
}

const DoctorList = ({
  title,
  doctors,
}: {
  title: string;
  doctors: DoctorMini[];
}) => (
  <div className="bg-gray-50 rounded-lg p-3">
    <h4 className="font-medium text-sm text-gray-700 mb-2">{title}</h4>
    {doctors.length === 0 ? (
      <p className="text-sm text-gray-400 italic">None available</p>
    ) : (
      <ul className="space-y-1">
        {doctors.map((doctor) => (
          <li key={doctor.id} className="text-sm">
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
}: DayDrilldownModalProps) => {
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <Card className="w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="text-xl">
              {monthName} {day}, {year}
            </CardTitle>
            {data && (
              <span
                className={`inline-block mt-2 px-2 py-1 text-xs font-medium rounded ${getRiskBadgeColor(
                  data.risk,
                )}`}
              >
                {data.risk.toUpperCase()}
              </span>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-5 w-5" />
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : error ? (
            <div className="text-center py-8 text-red-600">{error}</div>
          ) : data ? (
            <>
              {/* Risk Issues */}
              {data.risk !== "ok" && data.risk_issues.length > 0 && (
                <div
                  className={`mb-4 p-3 rounded-lg ${
                    data.risk === "critical"
                      ? "bg-red-50 border border-red-200"
                      : "bg-yellow-50 border border-yellow-200"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle
                      className={`h-4 w-4 ${
                        data.risk === "critical"
                          ? "text-red-600"
                          : "text-yellow-600"
                      }`}
                    />
                    <span
                      className={`font-medium text-sm ${
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
                  <ul className="space-y-1">
                    {data.risk_issues.map((issue, idx) => (
                      <li
                        key={idx}
                        className={`text-sm ${
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
                  <div className="mb-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
                    <p className="text-sm text-gray-700">
                      <strong>Gaps will be created for:</strong>{" "}
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
              <div className="mb-4">
                <div className="flex items-center gap-2 mb-3">
                  <Users className="h-4 w-4 text-gray-500" />
                  <h3 className="font-medium text-gray-700">
                    Available Doctors
                  </h3>
                </div>
                <div className="grid grid-cols-2 gap-3">
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
              <div className="flex gap-3 pt-4 border-t">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={handleEditDoctors}
                >
                  <Pencil className="h-4 w-4 mr-2" />
                  Edit Active Doctors
                </Button>
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={handleEditPreferences}
                >
                  <Pencil className="h-4 w-4 mr-2" />
                  Edit Monthly Preferences
                </Button>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
};
