import { Input } from "../ui/input";
import { InfoTooltip } from "./InfoTooltip";
import { type ValidationError, hasFieldError } from "./validation";
import { cn } from "../../lib/utils";

interface ShiftCountsGridProps {
  // On-site
  maxOnsiteTotal: number | null;
  targetOnsiteTotal: number | null;
  maxOnsiteWeekends: number | null;
  targetOnsiteWeekends: number | null;

  // On-call
  maxOncallTotal: number | null;
  targetOncallTotal: number | null;
  maxOncallWeekends: number | null;
  targetOncallWeekends: number | null;

  onChange: (field: string, value: number | null) => void;
  disabled?: boolean;
  errors?: ValidationError[];
}

export const ShiftCountsGrid = ({
  maxOnsiteTotal,
  targetOnsiteTotal,
  maxOnsiteWeekends,
  targetOnsiteWeekends,
  maxOncallTotal,
  targetOncallTotal,
  maxOncallWeekends,
  targetOncallWeekends,
  onChange,
  disabled = false,
  errors = [],
}: ShiftCountsGridProps) => {
  const handleChange = (field: string, value: string) => {
    const parsedValue = value ? parseInt(value, 10) : null;
    onChange(field, parsedValue);
  };

  const getInputClass = (field: string) => {
    return cn(
      "text-center h-8 sm:h-9 text-sm",
      hasFieldError(errors, field) && "border-red-500 focus:ring-red-500"
    );
  };

  const renderGrid = (
    label: string,
    fields: {
      maxTotal: { value: number | null; field: string };
      targetTotal: { value: number | null; field: string };
      maxWeekends: { value: number | null; field: string };
      targetWeekends: { value: number | null; field: string };
    }
  ) => (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </h4>
      <div className="grid grid-cols-[1fr_64px_64px] sm:grid-cols-3 gap-1.5 sm:gap-2 items-center">
        <div />
        <div className="text-center text-[11px] sm:text-sm font-medium text-gray-500">
          Total
        </div>
        <div className="text-center text-[11px] sm:text-sm font-medium text-gray-500">
          Weekend
        </div>

        <div className="text-xs sm:text-sm text-gray-600">
          <span className="sm:hidden">max</span>
          <span className="hidden sm:inline">my maximum</span>
        </div>
        <Input
          type="number"
          min="0"
          value={fields.maxTotal.value ?? ""}
          onChange={(e) => handleChange(fields.maxTotal.field, e.target.value)}
          disabled={disabled}
          placeholder=""
          className={getInputClass(fields.maxTotal.field)}
        />
        <Input
          type="number"
          min="0"
          value={fields.maxWeekends.value ?? ""}
          onChange={(e) =>
            handleChange(fields.maxWeekends.field, e.target.value)
          }
          disabled={disabled}
          placeholder=""
          className={getInputClass(fields.maxWeekends.field)}
        />

        <div className="text-xs sm:text-sm text-gray-600">
          <span className="sm:hidden">optimum</span>
          <span className="hidden sm:inline">my optimum</span>
        </div>
        <Input
          type="number"
          min="0"
          value={fields.targetTotal.value ?? ""}
          onChange={(e) =>
            handleChange(fields.targetTotal.field, e.target.value)
          }
          disabled={disabled}
          placeholder=""
          className={getInputClass(fields.targetTotal.field)}
        />
        <Input
          type="number"
          min="0"
          value={fields.targetWeekends.value ?? ""}
          onChange={(e) =>
            handleChange(fields.targetWeekends.field, e.target.value)
          }
          disabled={disabled}
          placeholder=""
          className={getInputClass(fields.targetWeekends.field)}
        />
      </div>
    </div>
  );

  return (
    <div className="rounded-lg border border-gray-200 p-3 sm:p-4 space-y-3 sm:space-y-4 bg-white">
      <div className="flex items-center gap-2">
        <h3 className="text-sm sm:text-base font-semibold">How many shifts?</h3>
        <InfoTooltip content="Set your preferred (my optimum) and maximum (my maximum) shifts. 'My optimum' is your ideal number, 'my maximum' is the absolute limit you can handle. Leave blank if flexible." />
      </div>

      {renderGrid("on-site", {
        maxTotal: { value: maxOnsiteTotal, field: "max_onsite_total" },
        targetTotal: { value: targetOnsiteTotal, field: "target_onsite_total" },
        maxWeekends: {
          value: maxOnsiteWeekends,
          field: "max_onsite_weekends",
        },
        targetWeekends: {
          value: targetOnsiteWeekends,
          field: "target_onsite_weekends",
        },
      })}

      {renderGrid("on-call", {
        maxTotal: { value: maxOncallTotal, field: "max_oncall_total" },
        targetTotal: { value: targetOncallTotal, field: "target_oncall_total" },
        maxWeekends: {
          value: maxOncallWeekends,
          field: "max_oncall_weekends",
        },
        targetWeekends: {
          value: targetOncallWeekends,
          field: "target_oncall_weekends",
        },
      })}
    </div>
  );
};
