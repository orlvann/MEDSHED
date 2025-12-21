import { useState, useEffect } from "react";
import { Clock, Palmtree } from "lucide-react";
import { Button } from "../ui/button";
import { getTimeRemaining, type TimeRemaining } from "./types";
import type { PreferenceStatus } from "../../types";

interface StatusCountdownProps {
  status: PreferenceStatus;
  deadline: string | null;
  onSetAllOnsiteOff: () => void;
  onSetAllOncallOff: () => void;
  onResetAll: () => void;
  onMarkVacation: () => void;
  mode: "admin" | "doctor";
}

export const StatusCountdown = ({
  status,
  deadline,
  onSetAllOnsiteOff,
  onSetAllOncallOff,
  onResetAll,
  onMarkVacation,
  mode,
}: StatusCountdownProps) => {
  const [timeRemaining, setTimeRemaining] = useState<TimeRemaining | null>(
    getTimeRemaining(deadline)
  );

  // Update countdown every minute
  useEffect(() => {
    if (!deadline) return;

    const updateTime = () => {
      setTimeRemaining(getTimeRemaining(deadline));
    };

    updateTime();
    const interval = setInterval(updateTime, 60000); // Update every minute

    return () => clearInterval(interval);
  }, [deadline]);

  const isLocked = timeRemaining?.isPast || !deadline;
  const isDisabled = isLocked && mode === "doctor";

  return (
    <div className="space-y-4">
      {/* Status badge */}
      <div className="text-sm">
        <span className="text-gray-600">Status: </span>
        <span
          className={
            status === "submitted"
              ? "text-green-600 font-medium"
              : "text-red-600 font-medium"
          }
        >
          {status === "submitted" ? "Submitted" : "Your schedule is missing"}
        </span>
      </div>

      {/* Countdown timer */}
      {deadline && timeRemaining && !timeRemaining.isPast && (
        <div className="flex items-center gap-2 text-primary">
          <Clock className="h-5 w-5" />
          <span className="font-medium">
            <span className="text-lg">{timeRemaining.days}</span>{" "}
            <span className="text-sm">days</span>{" "}
            <span className="text-lg">{timeRemaining.hours}</span>{" "}
            <span className="text-sm">hours</span>{" "}
            <span className="text-lg">{timeRemaining.minutes}</span>{" "}
            <span className="text-sm">minutes</span>
          </span>
        </div>
      )}

      {deadline && (
        <p className="text-xs text-muted-foreground">
          Left to submit your schedule
          <br />
          After that time form is locked
        </p>
      )}

      {!deadline && (
        <p className="text-xs text-muted-foreground italic">
          No deadline set for this period
        </p>
      )}

      {/* Action buttons */}
      <div className="space-y-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={onMarkVacation}
          disabled={isDisabled}
        >
          <Palmtree className="h-4 w-4 mr-2" />
          Mark vacation
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={onSetAllOnsiteOff}
          disabled={isDisabled}
        >
          All on-site duties off
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={onSetAllOncallOff}
          disabled={isDisabled}
        >
          All on-call duties off
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={onResetAll}
          disabled={isDisabled}
        >
          Reset all
        </Button>
      </div>
    </div>
  );
};
