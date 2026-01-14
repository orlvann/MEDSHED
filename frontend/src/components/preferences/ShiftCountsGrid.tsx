import { Input } from "../ui/input";
import { Card, CardContent } from "../ui/card";
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
            <InfoTooltip content="Set your preferred (my optimum) and maximum (my maximum) shifts. 'My optimum' is your ideal number, 'my maximum' is the absolute limit you can handle. Leave blank if flexible—we'll schedule using fairness rules." />
          </div>

          {/* On-site grid */}
          <div className="space-y-2">
            <h4 className="text-sm font-semibold text-gray-900">on-site</h4>
            <div className="grid grid-cols-3 gap-3 items-center">
              {/* Headers */}
              <div></div>
              <div className="text-center text-sm font-medium text-gray-600">
                Weekday
              </div>
              <div className="text-center text-sm font-medium text-gray-600">
                Weekend
              </div>

              {/* my maximum row */}
              <div className="text-sm text-gray-700">my maximum</div>
              <Input
                type="number"
                min="0"
                value={maxOnsiteTotal ?? ""}
                onChange={(e) =>
                  handleChange("max_onsite_total", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_onsite_total")}
              />
              <Input
                type="number"
                min="0"
                value={maxOnsiteWeekends ?? ""}
                onChange={(e) =>
                  handleChange("max_onsite_weekends", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_onsite_weekends")}
              />

              {/* my optimum row */}
              <div className="text-sm text-gray-700">my optimum</div>
              <Input
                type="number"
                min="0"
                value={targetOnsiteTotal ?? ""}
                onChange={(e) =>
                  handleChange("target_onsite_total", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_onsite_total")}
              />
              <Input
                type="number"
                min="0"
                value={targetOnsiteWeekends ?? ""}
                onChange={(e) =>
                  handleChange("target_onsite_weekends", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_onsite_weekends")}
              />
            </div>
          </div>

          {/* On-call grid */}
          <div className="space-y-2">
            <h4 className="text-sm font-semibold text-gray-900">on-call</h4>
            <div className="grid grid-cols-3 gap-3 items-center">
              {/* Headers */}
              <div></div>
              <div className="text-center text-sm font-medium text-gray-600">
                Weekday
              </div>
              <div className="text-center text-sm font-medium text-gray-600">
                Weekend
              </div>

              {/* my maximum row */}
              <div className="text-sm text-gray-700">my maximum</div>
              <Input
                type="number"
                min="0"
                value={maxOncallTotal ?? ""}
                onChange={(e) =>
                  handleChange("max_oncall_total", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_oncall_total")}
              />
              <Input
                type="number"
                min="0"
                value={maxOncallWeekends ?? ""}
                onChange={(e) =>
                  handleChange("max_oncall_weekends", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("max_oncall_weekends")}
              />

              {/* my optimum row */}
              <div className="text-sm text-gray-700">my optimum</div>
              <Input
                type="number"
                min="0"
                value={targetOncallTotal ?? ""}
                onChange={(e) =>
                  handleChange("target_oncall_total", e.target.value)
                }
                disabled={disabled}
                placeholder=""
                className={getInputClass("target_oncall_total")}
              />
              <Input
                type="number"
                min="0"
                value={targetOncallWeekends ?? ""}
                onChange={(e) =>
                  handleChange("target_oncall_weekends", e.target.value)
                }
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
