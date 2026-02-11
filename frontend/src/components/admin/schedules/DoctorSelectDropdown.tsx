import { useEffect, useRef, useState, useLayoutEffect } from "react";
import type { DoctorSnapshotRead } from "../../../types";

interface DoctorSelectDropdownProps {
  doctors: Record<number, DoctorSnapshotRead>;
  participantDoctorIds: number[];
  currentDoctorId: number;
  onSelect: (doctorId: number) => void;
  onClose: () => void;
}

export const DoctorSelectDropdown = ({
  doctors,
  participantDoctorIds,
  currentDoctorId,
  onSelect,
  onClose,
}: DoctorSelectDropdownProps) => {
  const ref = useRef<HTMLDivElement>(null);
  const [openUpward, setOpenUpward] = useState(false);

  // Decide direction: if the dropdown would overflow the viewport, flip upward
  useLayoutEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.top;
    // If less than 260px (max-h-60 = 240px + margin) of space below, open upward
    if (spaceBelow < 260) {
      setOpenUpward(true);
    }
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  const sortedDoctors = participantDoctorIds
    .map((id) => ({ id, snapshot: doctors[id] }))
    .filter((d) => d.snapshot)
    .sort((a, b) =>
      a.snapshot.display_name.localeCompare(b.snapshot.display_name)
    );

  return (
    <div
      ref={ref}
      className={`absolute z-50 w-56 bg-white border border-gray-200 rounded-md shadow-lg max-h-60 overflow-y-auto ${
        openUpward ? "bottom-full mb-1" : "mt-1"
      }`}
    >
      {sortedDoctors.map(({ id, snapshot }) => (
        <button
          key={id}
          className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-100 flex items-center gap-2 ${
            id === currentDoctorId ? "bg-blue-50 font-medium" : ""
          }`}
          onClick={() => {
            onSelect(id);
            onClose();
          }}
        >
          <span
            className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${
              snapshot.role === "specialist"
                ? "bg-blue-500"
                : "bg-emerald-500"
            }`}
          />
          <span className="truncate">{snapshot.display_name}</span>
          {id === currentDoctorId && (
            <span className="ml-auto text-blue-600 text-xs">current</span>
          )}
        </button>
      ))}
      {sortedDoctors.length === 0 && (
        <div className="px-3 py-2 text-sm text-muted-foreground">
          No doctors available
        </div>
      )}
    </div>
  );
};
