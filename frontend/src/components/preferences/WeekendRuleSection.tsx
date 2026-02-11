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
    <div className="rounded-lg border border-gray-200 p-3 sm:p-4 bg-white">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          id="weekend_rule"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
          className="h-4 w-4 sm:h-5 sm:w-5 rounded border-gray-300 text-primary focus:ring-primary disabled:opacity-50 mt-0.5 flex-shrink-0"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Label
              htmlFor="weekend_rule"
              className={`text-sm sm:text-base font-semibold leading-tight ${
                disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
              }`}
            >
              Weekend rest rule exception
            </Label>
            <InfoTooltip content="If you check this, the system may schedule you for two consecutive days during one weekend (one on-site duty and one on-call) when it helps the overall schedule" />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            I am OK with an intense weekend
          </p>
        </div>
      </div>
    </div>
  );
};
