import { useState } from "react";
import { X } from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { getDaysInMonth } from "./types";

export interface VacationPeriod {
  startDay: number;
  endDay: number;
}

interface VacationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (vacation: VacationPeriod) => void;
  year: number;
  month: number;
  existingVacation?: VacationPeriod | null;
}

export const VacationModal = ({
  isOpen,
  onClose,
  onSave,
  year,
  month,
  existingVacation,
}: VacationModalProps) => {
  const daysInMonth = getDaysInMonth(year, month);
  const [startDay, setStartDay] = useState<string>(
    existingVacation?.startDay?.toString() ?? ""
  );
  const [endDay, setEndDay] = useState<string>(
    existingVacation?.endDay?.toString() ?? ""
  );
  const [error, setError] = useState("");

  if (!isOpen) return null;

  const handleSave = () => {
    const start = parseInt(startDay, 10);
    const end = parseInt(endDay, 10);

    // Validation
    if (!startDay || !endDay) {
      setError("Please enter both start and end dates");
      return;
    }

    if (isNaN(start) || isNaN(end)) {
      setError("Please enter valid day numbers");
      return;
    }

    if (start < 1 || start > daysInMonth || end < 1 || end > daysInMonth) {
      setError(`Days must be between 1 and ${daysInMonth}`);
      return;
    }

    if (start > end) {
      setError("Start day must be before or equal to end day");
      return;
    }

    setError("");
    onSave({ startDay: start, endDay: end });
    onClose();
  };

  const handleClearVacation = () => {
    onSave({ startDay: 0, endDay: 0 }); // Signal to clear vacation
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <Card className="w-full max-w-md mx-4">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-lg">Mark Vacation Period</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Select the vacation period. Days in vacation will be marked as unavailable
            for both on-site and on-call duties and cannot be modified.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="startDay">From (day)</Label>
              <Input
                id="startDay"
                type="number"
                min={1}
                max={daysInMonth}
                value={startDay}
                onChange={(e) => setStartDay(e.target.value)}
                placeholder={`1-${daysInMonth}`}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="endDay">To (day)</Label>
              <Input
                id="endDay"
                type="number"
                min={1}
                max={daysInMonth}
                value={endDay}
                onChange={(e) => setEndDay(e.target.value)}
                placeholder={`1-${daysInMonth}`}
              />
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <div className="flex justify-between pt-2">
            {existingVacation && existingVacation.startDay > 0 && (
              <Button variant="outline" onClick={handleClearVacation}>
                Clear Vacation
              </Button>
            )}
            <div className="flex gap-2 ml-auto">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={handleSave}>
                Save
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
