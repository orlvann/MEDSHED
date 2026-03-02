import { useState, useCallback, useMemo } from "react";
import { Button } from "../../ui/button";
import { Download, FileText, FileSpreadsheet, X } from "lucide-react";
import { schedulesApi } from "../../../services/api";
import type { DoctorSnapshotRead } from "../../../types";

interface AdminExportPanelProps {
  year: number;
  month: number;
  doctors: Record<number, DoctorSnapshotRead>;
  onClose: () => void;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const AdminExportPanel = ({
  year,
  month,
  doctors,
  onClose,
}: AdminExportPanelProps) => {
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const pad = String(month).padStart(2, "0");

  const sortedDoctors = useMemo(() => {
    return [...Object.entries(doctors)]
      .map(([id, snap]) => ({ id: Number(id), ...snap }))
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [doctors]);

  const totalCount = sortedDoctors.length;
  const allSelected = selectedIds.length === totalCount && totalCount > 0;

  const toggleAll = () => {
    if (allSelected || selectedIds.length > 0) {
      setSelectedIds([]);
    } else {
      setSelectedIds(sortedDoctors.map((d) => d.id));
    }
  };

  const toggleDoctor = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleExport = useCallback(
    async (format: "xlsx" | "pdf") => {
      if (downloading) return;
      setDownloading(format);
      setError(null);
      try {
        const ids = selectedIds.length > 0 && selectedIds.length < totalCount
          ? selectedIds
          : undefined;
        const blob = await schedulesApi.adminExport(year, month, format, ids);
        const filename = `schedule-${year}-${pad}.${format}`;
        triggerDownload(blob, filename);
        onClose();
      } catch {
        setError(
          "Export failed. Make sure a published schedule exists for this period."
        );
      } finally {
        setDownloading(null);
      }
    },
    [year, month, pad, downloading, onClose, selectedIds, totalCount]
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Export Schedule</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-sm text-muted-foreground mb-4">
          Download the published schedule for{" "}
          {new Date(year, month - 1).toLocaleString("en-US", {
            month: "long",
            year: "numeric",
          })}
          .
        </p>

        {/* Doctor filter */}
        {totalCount > 0 && (
          <div className="mb-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-medium text-gray-700">
                Filter by doctor
              </span>
              <button
                type="button"
                onClick={toggleAll}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                {selectedIds.length > 0 ? "Clear" : "Select all"}
              </button>
            </div>

            <div className="border border-gray-200 rounded-lg max-h-40 overflow-y-auto">
              {sortedDoctors.map((doc) => {
                const checked = selectedIds.includes(doc.id);
                return (
                  <label
                    key={doc.id}
                    className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleDoctor(doc.id)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 h-3.5 w-3.5"
                    />
                    <span
                      className={`h-2 w-2 rounded-full shrink-0 ${
                        doc.role === "specialist"
                          ? "bg-violet-500"
                          : "bg-emerald-500"
                      }`}
                    />
                    <span className="truncate">{doc.display_name}</span>
                  </label>
                );
              })}
            </div>

            <p className="text-xs text-muted-foreground mt-1">
              {selectedIds.length === 0 || selectedIds.length === totalCount
                ? "All doctors"
                : `${selectedIds.length} of ${totalCount} selected`}
            </p>
          </div>
        )}

        {error && (
          <div className="mb-3 p-2.5 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg">
            {error}
          </div>
        )}

        <div className="space-y-2">
          <Button
            variant="outline"
            className="w-full justify-start gap-3 h-11"
            onClick={() => handleExport("pdf")}
            disabled={downloading !== null}
          >
            <FileText className="h-4 w-4 text-red-500" />
            <span className="flex-1 text-left">
              {downloading === "pdf" ? "Downloading..." : "Download PDF"}
            </span>
            <Download className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>

          <Button
            variant="outline"
            className="w-full justify-start gap-3 h-11"
            onClick={() => handleExport("xlsx")}
            disabled={downloading !== null}
          >
            <FileSpreadsheet className="h-4 w-4 text-green-600" />
            <span className="flex-1 text-left">
              {downloading === "xlsx" ? "Downloading..." : "Download Excel"}
            </span>
            <Download className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
      </div>
    </div>
  );
};
