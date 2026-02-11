import { Star } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "../../ui/sheet";
import type { DoctorSnapshotRead, ShiftType } from "../../../types";

const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

interface DayEditSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: number;
  month: number;
  day: number;
  doctors: Record<number, DoctorSnapshotRead>;
  participantDoctorIds: number[];
  onsiteDoctorId: number | undefined;
  oncallDoctorId: number | undefined;
  readOnly: boolean;
  onAssignmentChange?: (
    day: number,
    shiftType: ShiftType,
    newDoctorId: number
  ) => void;
}

function RoleBadge({ role }: { role: string }) {
  const isSpecialist = role === "specialist";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider leading-none ${
        isSpecialist
          ? "bg-violet-100 text-violet-700"
          : "bg-teal-100 text-teal-700"
      }`}
    >
      {isSpecialist ? "SP" : "RE"}
    </span>
  );
}

function HeadBadge() {
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 leading-none">
      <Star className="h-2.5 w-2.5 fill-amber-500 text-amber-500" />
      Head
    </span>
  );
}

function DoctorListSection({
  label,
  dotColor,
  accentBg,
  doctors,
  participantDoctorIds,
  currentDoctorId,
  readOnly,
  onSelect,
}: {
  label: string;
  dotColor: string;
  accentBg: string;
  doctors: Record<number, DoctorSnapshotRead>;
  participantDoctorIds: number[];
  currentDoctorId: number | undefined;
  readOnly: boolean;
  onSelect: (doctorId: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className={`inline-block w-2.5 h-2.5 rounded-full ${dotColor}`} />
        <span className="text-sm font-semibold text-gray-700">{label}</span>
      </div>
      <div className="space-y-1 max-h-[30vh] overflow-y-auto">
        {participantDoctorIds.map((id) => {
          const doc = doctors[id];
          if (!doc) return null;
          const isCurrent = id === currentDoctorId;
          return (
            <button
              key={id}
              type="button"
              disabled={readOnly}
              onClick={() => onSelect(id)}
              className={`flex items-center gap-2 w-full px-3 py-2.5 rounded-lg text-left transition-colors ${
                isCurrent
                  ? `${accentBg} ring-1 ring-inset ring-current/10`
                  : readOnly
                    ? "bg-gray-50"
                    : "bg-gray-50 active:bg-gray-100"
              }`}
            >
              <span className="font-medium text-sm text-gray-800 truncate flex-1">
                {doc.display_name}
              </span>
              <span className="flex items-center gap-1 flex-shrink-0">
                <RoleBadge role={doc.role} />
                {doc.is_head && <HeadBadge />}
                {isCurrent && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-blue-700 leading-none">
                    Current
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DayEditSheet({
  open,
  onOpenChange,
  year,
  month,
  day,
  doctors,
  participantDoctorIds,
  onsiteDoctorId,
  oncallDoctorId,
  readOnly,
  onAssignmentChange,
}: DayEditSheetProps) {
  const jsDay = new Date(year, month - 1, day).getDay();
  const weekdayIdx = jsDay === 0 ? 6 : jsDay - 1;
  const weekdayName = WEEKDAY_NAMES[weekdayIdx];
  const monthName = MONTH_NAMES[month - 1];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="rounded-t-xl max-h-[85vh] px-4 pb-6 pt-4"
      >
        <SheetHeader className="text-left mb-4">
          <SheetTitle className="text-lg">
            {weekdayName}, {day}
          </SheetTitle>
          <SheetDescription>
            {monthName} {year}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-5 overflow-y-auto">
          <DoctorListSection
            label="Onsite"
            dotColor="bg-teal-500"
            accentBg="bg-teal-50"
            doctors={doctors}
            participantDoctorIds={participantDoctorIds}
            currentDoctorId={onsiteDoctorId}
            readOnly={readOnly}
            onSelect={(id) => onAssignmentChange?.(day, "onsite", id)}
          />
          <DoctorListSection
            label="Oncall"
            dotColor="bg-amber-500"
            accentBg="bg-amber-50"
            doctors={doctors}
            participantDoctorIds={participantDoctorIds}
            currentDoctorId={oncallDoctorId}
            readOnly={readOnly}
            onSelect={(id) => onAssignmentChange?.(day, "oncall", id)}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
