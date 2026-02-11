import { useState, useEffect } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { getDaysInMonth, type VacationPeriod } from "./types";

interface VacationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (vacations: VacationPeriod[]) => void;
  year: number;
  month: number;
  existingVacations?: VacationPeriod[];
}

export const VacationModal = ({
  isOpen,
  onClose,
  onSave,
  year,
  month,
  existingVacations = [],
}: VacationModalProps) => {
  const daysInMonth = getDaysInMonth(year, month);
  const [periods, setPeriods] = useState<VacationPeriod[]>([]);
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [error, setError] = useState("");

  // Initialize periods when modal opens
  useEffect(() => {
    if (isOpen) {
      setPeriods(existingVacations.length > 0 ? [...existingVacations] : []);
      setNewStart("");
      setNewEnd("");
      setError("");
    }
  }, [isOpen, existingVacations]);

  if (!isOpen) return null;

  const validatePeriod = (start: number, end: number, excludeIndex?: number): string | null => {
    if (start < 1 || start > daysInMonth || end < 1 || end > daysInMonth) {
      return `Days must be between 1 and ${daysInMonth}`;
    }

    if (start > end) {
      return "Start day must be before or equal to end day";
    }

    // Check overlap with other periods
    for (let i = 0; i < periods.length; i++) {
      if (i === excludeIndex) continue;
      const other = periods[i];
      if (!(end < other.startDay || start > other.endDay)) {
        return `Overlaps with existing vacation (${other.startDay}-${other.endDay})`;
      }
    }

    return null;
  };

  const handleAddPeriod = () => {
    const start = parseInt(newStart, 10);
    const end = parseInt(newEnd, 10);

    if (!newStart || !newEnd) {
      setError("Please enter both start and end days");
      return;
    }

    if (isNaN(start) || isNaN(end)) {
      setError("Please enter valid day numbers");
      return;
    }

    const validationError = validatePeriod(start, end);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError("");
    setPeriods([...periods, { startDay: start, endDay: end }].sort((a, b) => a.startDay - b.startDay));
    setNewStart("");
    setNewEnd("");
  };

  const handleDeletePeriod = (index: number) => {
    setPeriods(periods.filter((_, i) => i !== index));
  };

  const handleClearAll = () => {
    setPeriods([]);
  };

  const handleSave = () => {
    onSave(periods);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-end sm:items-center justify-center z-[60]">
      <Card className="w-full max-w-md mx-0 sm:mx-4 rounded-t-lg sm:rounded-lg max-h-[90vh] overflow-y-auto">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-lg">Mark Vacation Periods</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Add vacation periods. Days in vacation will be marked as unavailable
            for both on-site and on-call duties.
          </p>

          {/* Existing periods */}
          {periods.length > 0 && (
            <div className="space-y-2">
              <Label>Current vacation periods:</Label>
              <div className="space-y-1">
                {periods.map((period, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between bg-purple-50 text-purple-700 px-3 py-2 rounded-md"
                  >
                    <span>
                      Day {period.startDay} - {period.endDay}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeletePeriod(index)}
                      className="h-6 w-6 p-0 hover:bg-purple-100"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Add new period */}
          <div className="space-y-2">
            <Label>Add new period:</Label>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Label htmlFor="startDay" className="text-xs text-muted-foreground">From</Label>
                <Input
                  id="startDay"
                  type="number"
                  min={1}
                  max={daysInMonth}
                  value={newStart}
                  onChange={(e) => setNewStart(e.target.value)}
                  placeholder={`1-${daysInMonth}`}
                />
              </div>
              <div className="flex-1">
                <Label htmlFor="endDay" className="text-xs text-muted-foreground">To</Label>
                <Input
                  id="endDay"
                  type="number"
                  min={1}
                  max={daysInMonth}
                  value={newEnd}
                  onChange={(e) => setNewEnd(e.target.value)}
                  placeholder={`1-${daysInMonth}`}
                />
              </div>
              <Button onClick={handleAddPeriod} size="sm" className="h-10">
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <div className="flex justify-between pt-2">
            {periods.length > 0 && (
              <Button variant="outline" onClick={handleClearAll}>
                Clear All
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
