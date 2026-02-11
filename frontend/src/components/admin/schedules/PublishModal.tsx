import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../ui/dialog";
import { Button } from "../../ui/button";
import { AlertTriangle, Send } from "lucide-react";
import type {
  DiagnosticsRead,
  DiagnosticsFindingRead,
  AcceptedException,
} from "../../../types";

interface PublishModalProps {
  open: boolean;
  onClose: () => void;
  onPublish: (
    force: boolean,
    note: string,
    acceptedExceptions: AcceptedException[]
  ) => void;
  diagnostics: DiagnosticsRead | null;
  publishing: boolean;
}

export const PublishModal = ({
  open,
  onClose,
  onPublish,
  diagnostics,
  publishing,
}: PublishModalProps) => {
  const [note, setNote] = useState("");

  const summary = diagnostics?.summary;
  const findings = diagnostics?.details?.findings || [];
  const hasHardIssues = (summary?.hard_issues_count ?? 0) > 0;
  const criticalFindings = findings.filter(
    (f: DiagnosticsFindingRead) => f.severity === "critical"
  );

  const handlePublish = () => {
    if (hasHardIssues) {
      // Force publish: auto-populate accepted_exceptions from critical findings
      const exceptions: AcceptedException[] = criticalFindings.map(
        (f: DiagnosticsFindingRead) => ({
          code: f.code,
          justification: note || "Force-published by admin",
        })
      );
      onPublish(true, note, exceptions);
    } else {
      onPublish(false, note, []);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Publish Schedule</DialogTitle>
          <DialogDescription>
            This will make the schedule visible to all doctors.
          </DialogDescription>
        </DialogHeader>

        {summary && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between bg-gray-50 rounded p-2">
                <span className="text-muted-foreground">Coverage Gaps</span>
                <span
                  className={
                    summary.coverage_missing_required_slots > 0
                      ? "font-medium text-red-600"
                      : "text-green-600"
                  }
                >
                  {summary.coverage_missing_required_slots}
                </span>
              </div>
              <div className="flex justify-between bg-gray-50 rounded p-2">
                <span className="text-muted-foreground">Hard Issues</span>
                <span
                  className={
                    summary.hard_issues_count > 0
                      ? "font-medium text-red-600"
                      : "text-green-600"
                  }
                >
                  {summary.hard_issues_count}
                </span>
              </div>
              <div className="flex justify-between bg-gray-50 rounded p-2">
                <span className="text-muted-foreground">Rest Violations</span>
                <span
                  className={
                    summary.rest_violations > 0
                      ? "text-yellow-600"
                      : "text-green-600"
                  }
                >
                  {summary.rest_violations}
                </span>
              </div>
              <div className="flex justify-between bg-gray-50 rounded p-2">
                <span className="text-muted-foreground">Pref. Fulfillment</span>
                <span>{Math.round(summary.preference_fulfillment_pct)}%</span>
              </div>
            </div>

            {hasHardIssues && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3">
                <AlertTriangle className="h-4 w-4 mt-0.5 text-red-600 flex-shrink-0" />
                <div className="text-sm text-red-800">
                  <strong>Hard issues detected.</strong> Publishing will require
                  force mode. All critical findings will be accepted as
                  exceptions.
                </div>
              </div>
            )}
          </div>
        )}

        <div>
          <label className="text-sm font-medium" htmlFor="publish-note">
            Note (optional)
          </label>
          <textarea
            id="publish-note"
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none"
            rows={2}
            placeholder="Add a note about this publication..."
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={publishing}>
            Cancel
          </Button>
          <Button
            onClick={handlePublish}
            disabled={publishing}
            variant={hasHardIssues ? "destructive" : "default"}
          >
            <Send className="h-4 w-4 mr-2" />
            {publishing
              ? "Publishing..."
              : hasHardIssues
                ? "Force Publish"
                : "Publish"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
