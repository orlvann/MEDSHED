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
    <div className="fixed inset-0 bg-black/50 flex items-end sm:items-center justify-center z-50">
      <Card className="w-full max-w-lg mx-0 sm:mx-4 rounded-t-lg sm:rounded-lg max-h-[90vh] overflow-y-auto">
        <CardHeader className="px-4 py-3 sm:px-6 sm:py-4 flex flex-row items-start justify-between space-y-0 pb-2">
          <div className="flex items-center gap-2.5 sm:gap-3">
            <div className="p-1.5 sm:p-2 bg-red-100 rounded-full">
              <AlertTriangle className="h-4 w-4 sm:h-5 sm:w-5 text-red-600" />
            </div>
            <div>
              <CardTitle className="text-base sm:text-lg">
                Coverage Issues
              </CardTitle>
              <CardDescription className="text-xs sm:text-sm">
                {monthName} {year}
              </CardDescription>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onCancel} className="h-8 w-8 p-0">
            <X className="h-4 w-4 sm:h-5 sm:w-5" />
          </Button>
        </CardHeader>
        <CardContent className="px-4 sm:px-6 pb-4 sm:pb-6">
          <div className="mb-3 sm:mb-4 p-2.5 sm:p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-xs sm:text-sm text-red-800">
              Some days can't be covered. Proceeding will leave gaps on these days.
            </p>
          </div>

          {/* List of critical days */}
          <div className="space-y-2 sm:space-y-3 mb-4 sm:mb-6">
            {criticalDays.map((day) => (
              <div
                key={day.day}
                className="p-2.5 sm:p-3 bg-gray-50 rounded-lg border border-gray-200"
              >
                <div className="font-medium text-xs sm:text-sm text-gray-900 mb-1.5 sm:mb-2">
                  Day {day.day}
                </div>

                {/* Issues */}
                {day.risk_issues.length > 0 && (
                  <ul className="mb-1.5 sm:mb-2 space-y-0.5 sm:space-y-1">
                    {day.risk_issues.map((issue, idx) => (
                      <li key={idx} className="text-xs sm:text-sm text-gray-600">
                        {getRiskIssueMessage(issue)}
                      </li>
                    ))}
                  </ul>
                )}

                {/* Gaps that will be created */}
                {day.suggested_ignored_slots.length > 0 && (
                  <div className="text-xs sm:text-sm">
                    <span className="font-medium text-red-700">
                      Gaps:{" "}
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
          <div className="mb-4 sm:mb-6 p-2.5 sm:p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-xs sm:text-sm text-yellow-800">
              <strong>Total gaps:</strong> {allIgnoredSlots.length} slot
              {allIgnoredSlots.length !== 1 ? "s" : ""} unassigned.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 sm:gap-3">
            <Button
              variant="outline"
              className="flex-1 h-8 text-xs sm:h-9 sm:text-sm"
              onClick={onCancel}
              disabled={generating}
            >
              Cancel
            </Button>
            <Button
              className="flex-1 h-8 text-xs sm:h-9 sm:text-sm bg-red-600 hover:bg-red-700"
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
