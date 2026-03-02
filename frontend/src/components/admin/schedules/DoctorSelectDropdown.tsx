import { useEffect, useRef, useState, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
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
  const anchorRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{
    top: number;
    left: number;
    openUpward: boolean;
  } | null>(null);

  // Position the dropdown relative to the anchor using viewport coordinates
  useLayoutEffect(() => {
    if (!anchorRef.current) return;
    const anchorRect = anchorRef.current.getBoundingClientRect();
    const dropdownHeight = 240; // max-h-60 = 240px
    const spaceBelow = window.innerHeight - anchorRect.bottom;
    const openUpward = spaceBelow < dropdownHeight + 8 && anchorRect.top > dropdownHeight;

    setPosition({
      top: openUpward
        ? anchorRect.top + window.scrollY - dropdownHeight - 4
        : anchorRect.bottom + window.scrollY + 4,
      left: anchorRect.left + window.scrollX,
      openUpward,
    });
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

  const dropdown = position
    ? createPortal(
        <div
          ref={ref}
          style={{
            position: "absolute",
            top: position.top,
            left: position.left,
            zIndex: 9999,
          }}
          className="w-56 bg-white border border-gray-200 rounded-md shadow-lg max-h-60 overflow-y-auto"
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
                className={`inline-block text-[10px] leading-none font-semibold px-1 py-0.5 rounded flex-shrink-0 ${
                  snapshot.role === "specialist"
                    ? "bg-violet-100 text-violet-700"
                    : "bg-emerald-100 text-emerald-700"
                }`}
              >
                {snapshot.role === "specialist" ? "SP" : "RE"}
              </span>
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
        </div>,
        document.body
      )
    : null;

  return (
    <>
      {/* Invisible anchor element to measure position */}
      <div ref={anchorRef} className="absolute left-0 right-0" />
      {dropdown}
    </>
  );
};
