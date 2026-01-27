import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "../../ui/card";
import { Button } from "../../ui/button";
import { AlertTriangle, X } from "lucide-react";
import { getRiskIssueMessage } from "./riskMessages";
import type { AvailabilityDayOverview, IgnoredSlot } from "../../../types";

interface IgnoreGapsModalProps {
  year: number;
  month: number;
  criticalDays: AvailabilityDayOverview[];
  onCancel: () => void;
  onAccept: (ignoreSlots: IgnoredSlot[]) => void;
  generating?: boolean;
}

export const IgnoreGapsModal = ({
  year,
  month,
  criticalDays,
  onCancel,
  onAccept,
  generating = false,
}: IgnoreGapsModalProps) => {
  const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
    month: "long",
  });

  // Collect all suggested_ignored_slots from critical days
  const allIgnoredSlots: IgnoredSlot[] = criticalDays.flatMap(
    (day) => day.suggested_ignored_slots,
  );

  const handleAccept = () => {
    onAccept(allIgnoredSlots);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <Card className="w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 rounded-full">
              <AlertTriangle className="h-5 w-5 text-red-600" />
            </div>
            <div>
              <CardTitle className="text-lg">
                Coverage Issues Detected
              </CardTitle>
              <CardDescription>
                {monthName} {year}
              </CardDescription>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            <X className="h-5 w-5" />
          </Button>
        </CardHeader>
        <CardContent>
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-800">
              Some days are impossible to cover with the current inputs. If you
              proceed, the schedule will have gaps (missing assignments) on the
              following days.
            </p>
          </div>

          {/* List of critical days */}
          <div className="space-y-3 mb-6">
            {criticalDays.map((day) => (
              <div
                key={day.day}
                className="p-3 bg-gray-50 rounded-lg border border-gray-200"
              >
                <div className="font-medium text-gray-900 mb-2">
                  Day {day.day}
                </div>

                {/* Issues */}
                {day.risk_issues.length > 0 && (
                  <ul className="mb-2 space-y-1">
                    {day.risk_issues.map((issue, idx) => (
                      <li key={idx} className="text-sm text-gray-600">
                        {getRiskIssueMessage(issue)}
                      </li>
                    ))}
                  </ul>
                )}

                {/* Gaps that will be created */}
                {day.suggested_ignored_slots.length > 0 && (
                  <div className="text-sm">
                    <span className="font-medium text-red-700">
                      Gaps will be created for:{" "}
                    </span>
                    <span className="text-red-600">
                      {day.suggested_ignored_slots
                        .map((slot) =>
                          slot.shift_type === "onsite" ? "On-site" : "On-call",
                        )
                        .join(", ")}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="mb-6 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800">
              <strong>Total gaps:</strong> {allIgnoredSlots.length} slot
              {allIgnoredSlots.length !== 1 ? "s" : ""} will be left unassigned.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <Button
              variant="outline"
              className="flex-1"
              onClick={onCancel}
              disabled={generating}
            >
              Cancel
            </Button>
            <Button
              className="flex-1 bg-red-600 hover:bg-red-700"
              onClick={handleAccept}
              disabled={generating}
            >
              {generating ? "Generating..." : "Accept & Generate"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
