import { Input } from "../ui/input";
import { Card, CardContent } from "../ui/card";
import { InfoTooltip } from "./InfoTooltip";

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
}: ShiftCountsGridProps) => {
  const handleChange = (field: string, value: string) => {
    onChange(field, value ? parseInt(value, 10) : null);
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
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                value={maxOnsiteWeekends ?? ""}
                onChange={(e) => handleChange("max_onsite_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className="text-center"
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
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                value={targetOnsiteWeekends ?? ""}
                onChange={(e) => handleChange("target_onsite_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className="text-center"
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
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                value={maxOncallWeekends ?? ""}
                onChange={(e) => handleChange("max_oncall_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className="text-center"
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
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                value={targetOncallWeekends ?? ""}
                onChange={(e) => handleChange("target_oncall_weekends", e.target.value)}
                disabled={disabled}
                placeholder=""
                className="text-center"
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
