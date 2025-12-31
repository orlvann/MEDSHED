import { useState, useRef, useEffect } from "react";
import { Button } from "../ui/button";
import { Download, FileText, FileSpreadsheet, Calendar } from "lucide-react";

export const ExportPanel = () => {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close panel when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  const handleExport = (format: string) => {
    alert(`${format} export: Coming soon!`);
    setOpen(false);
  };

  return (
    <div className="relative" ref={panelRef}>
      <Button variant="outline" size="sm" onClick={() => setOpen(!open)}>
        <Download className="h-4 w-4 mr-2" />
        Exports & Sync
      </Button>

      {open && (
        <div className="absolute right-0 bottom-full mb-2 bg-white border rounded-lg shadow-lg z-20 py-2 min-w-[200px]">
          <div className="px-3 py-1.5 text-xs font-semibold text-gray-500 uppercase">
            Exports & Sync
          </div>

          <button
            onClick={() => handleExport("PDF")}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 text-left"
          >
            <FileText className="h-4 w-4 text-gray-500" />
            <span>PDF</span>
            <Download className="h-3 w-3 text-gray-400 ml-auto" />
          </button>

          <button
            onClick={() => handleExport("Excel")}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 text-left"
          >
            <FileSpreadsheet className="h-4 w-4 text-gray-500" />
            <span>Excel</span>
            <Download className="h-3 w-3 text-gray-400 ml-auto" />
          </button>

          <div className="border-t my-1" />

          <button
            onClick={() => handleExport("Google Calendar")}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 text-left"
          >
            <Calendar className="h-4 w-4 text-blue-500" />
            <span>Sync to Google Calendar</span>
          </button>

          <button
            onClick={() => handleExport("Apple Calendar")}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 text-left"
          >
            <Calendar className="h-4 w-4 text-gray-500" />
            <span>Sync to Apple Calendar</span>
          </button>
        </div>
      )}
    </div>
  );
};
