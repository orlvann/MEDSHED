import { Input } from "../ui/input";
import { Card, CardContent } from "../ui/card";
import { InfoTooltip } from "./InfoTooltip";
import { type ValidationError, hasFieldError } from "./validation";
import { cn } from "../../lib/utils";

// Mapping of max fields to their corresponding target fields
const MAX_TO_TARGET_MAP: Record<string, string> = {
  max_onsite_total: "target_onsite_total",
  max_onsite_weekends: "target_onsite_weekends",
  max_oncall_total: "target_oncall_total",
  max_oncall_weekends: "target_oncall_weekends",
};

// Mapping of target fields to their corresponding max fields
const TARGET_TO_MAX_MAP: Record<string, string> = {
  target_onsite_total: "max_onsite_total",
  target_onsite_weekends: "max_onsite_weekends",
  target_oncall_total: "max_oncall_total",
  target_oncall_weekends: "max_oncall_weekends",
};

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
  // Get current values by field name
  const getValueByField = (field: string): number | null => {
    const fieldMap: Record<string, number | null> = {
      max_onsite_total: maxOnsiteTotal,
      target_onsite_total: targetOnsiteTotal,
      max_onsite_weekends: maxOnsiteWeekends,
      target_onsite_weekends: targetOnsiteWeekends,
      max_oncall_total: maxOncallTotal,
      target_oncall_total: targetOncallTotal,
      max_oncall_weekends: maxOncallWeekends,
      target_oncall_weekends: targetOncallWeekends,
    };
    return fieldMap[field] ?? null;
  };

  const handleChange = (field: string, value: string) => {
    const parsedValue = value ? parseInt(value, 10) : null;

    // If changing a max field, also clamp the corresponding target
    if (field in MAX_TO_TARGET_MAP && parsedValue !== null) {
      const targetField = MAX_TO_TARGET_MAP[field];
      const currentTarget = getValueByField(targetField);
      if (currentTarget !== null && currentTarget > parsedValue) {
        // Clamp target to new max value
        onChange(targetField, parsedValue);
      }
    }

    // If changing a target field, clamp it to the corresponding max
    if (field in TARGET_TO_MAX_MAP && parsedValue !== null) {
      const maxField = TARGET_TO_MAX_MAP[field];
      const currentMax = getValueByField(maxField);
      if (currentMax !== null && parsedValue > currentMax) {
        // Clamp to max value
        onChange(field, currentMax);
        return;
      }
    }

    onChange(field, parsedValue);
  };

  const getInputClass = (field: string) => {
    return cn(
      "text-center",
      hasFieldError(errors, field) && "border-red-500 focus:ring-red-500"
    );
  };

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">How many shifts?</h3>
            <InfoTooltip
              content="Optionally set your preferred (I want) and maximum (I can) on-site/on-call shifts for this month. Leave blank if you're flexible—we'll schedule using fairness rules."
            />
          </div>

          {/* On-site grid */}
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">on-site</h4>
            <div className="grid grid-cols-3 gap-3 items-center">
              {/* Headers */}
              <div></div>
              <div className="text-center text-sm font-medium text-gray-600">Weekday</div>
              <div className="text-center text-sm font-medium text-gray-600">Weekend</div>

              {/* I can row */}
              <div className="text-sm text-gray-700">I can</div>
              <Input
                type="number"
                min="0"
                value={maxOnsiteTotal ?? ""}
                onChange={(e) => handleChange("max_onsite_total", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_onsite_total")}
              />
              <Input
                type="number"
                min="0"
                value={maxOnsiteWeekends ?? ""}
                onChange={(e) => handleChange("max_onsite_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_onsite_weekends")}
              />

              {/* I want row */}
              <div className="text-sm text-gray-700">I want</div>
              <Input
                type="number"
                min="0"
                value={targetOnsiteTotal ?? ""}
                onChange={(e) => handleChange("target_onsite_total", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_onsite_total")}
              />
              <Input
                type="number"
                min="0"
                value={targetOnsiteWeekends ?? ""}
                onChange={(e) => handleChange("target_onsite_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_onsite_weekends")}
              />
            </div>
          </div>

          {/* On-call grid */}
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">on-call</h4>
            <div className="grid grid-cols-3 gap-3 items-center">
              {/* Headers */}
              <div></div>
              <div className="text-center text-sm font-medium text-gray-600">Weekday</div>
              <div className="text-center text-sm font-medium text-gray-600">Weekend</div>

              {/* I can row */}
              <div className="text-sm text-gray-700">I can</div>
              <Input
                type="number"
                min="0"
                value={maxOncallTotal ?? ""}
                onChange={(e) => handleChange("max_oncall_total", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_oncall_total")}
              />
              <Input
                type="number"
                min="0"
                value={maxOncallWeekends ?? ""}
                onChange={(e) => handleChange("max_oncall_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_oncall_weekends")}
              />

              {/* I want row */}
              <div className="text-sm text-gray-700">I want</div>
              <Input
                type="number"
                min="0"
                value={targetOncallTotal ?? ""}
                onChange={(e) => handleChange("target_oncall_total", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_oncall_total")}
              />
              <Input
                type="number"
                min="0"
                value={targetOncallWeekends ?? ""}
                onChange={(e) => handleChange("target_oncall_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_oncall_weekends")}
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
