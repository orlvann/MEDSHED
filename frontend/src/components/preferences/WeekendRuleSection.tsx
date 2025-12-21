import { Card, CardContent } from "../ui/card";
import { InfoTooltip } from "./InfoTooltip";
import { Label } from "../ui/label";

interface WeekendRuleSectionProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export const WeekendRuleSection = ({
  checked,
  onChange,
  disabled = false,
}: WeekendRuleSectionProps) => {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Weekend rest rule exception</h3>
            <InfoTooltip
              content="If you check this, the system may schedule you for two consecutive days during one weekend (one on-site duty and one on-call) when it helps the overall schedule"
            />
          </div>
          <div className="flex items-center space-x-3">
            <input
              type="checkbox"
              id="weekend_rule"
              checked={checked}
              onChange={(e) => onChange(e.target.checked)}
              disabled={disabled}
              className="h-5 w-5 rounded border-gray-300 text-primary focus:ring-primary disabled:opacity-50"
            />
            <Label
              htmlFor="weekend_rule"
              className={disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
            >
              I am OK with an intense weekend
            </Label>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
