import { InfoTooltip } from "./InfoTooltip";

interface AdditionalNoteProps {
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

export const AdditionalNote = ({
  value,
  onChange,
  disabled = false,
}: AdditionalNoteProps) => {
  return (
    <div className="rounded-lg border border-gray-200 p-3 sm:p-4 space-y-2 sm:space-y-3 bg-white">
      <div className="flex items-center gap-2">
        <h3 className="text-sm sm:text-base font-semibold">Additional note</h3>
        <InfoTooltip
          content={
            <>
              Optional message for the coordinator.
              <br />
              <span className="text-xs italic">
                Example: "If there's an urgent staffing shortage, I can
                exceptionally take one extra weekend shift."
              </span>
            </>
          }
        />
      </div>
      <textarea
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        placeholder="Type here..."
        disabled={disabled}
        className="w-full h-16 sm:h-28 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
      />
    </div>
  );
};
