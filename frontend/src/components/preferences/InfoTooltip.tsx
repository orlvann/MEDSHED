import { useState, useRef, useEffect } from "react";
import { Info } from "lucide-react";

interface InfoTooltipProps {
  content: string | React.ReactNode;
  className?: string;
}

export const InfoTooltip = ({ content, className = "" }: InfoTooltipProps) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<"top" | "bottom">("top");
  const tooltipRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isVisible && iconRef.current) {
      const rect = iconRef.current.getBoundingClientRect();
      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;

      // Show tooltip below if not enough space above
      if (spaceAbove < 100 && spaceBelow > spaceAbove) {
        setPosition("bottom");
      } else {
        setPosition("top");
      }
    }
  }, [isVisible]);

  return (
    <div className={`relative inline-flex items-center ${className}`}>
      <button
        ref={iconRef}
        type="button"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onClick={() => setIsVisible(!isVisible)}
        className="inline-flex items-center justify-center w-4 h-4 text-muted-foreground hover:text-foreground transition-colors"
        aria-label="More information"
      >
        <Info className="w-4 h-4" />
      </button>

      {isVisible && (
        <div
          ref={tooltipRef}
          className={`absolute z-50 px-3 py-2 text-[14px] leading-normal font-normal bg-popover text-popover-foreground border border-border rounded-md shadow-md min-w-[280px] max-w-sm whitespace-normal ${
            position === "top"
              ? "bottom-full mb-2 left-1/2 -translate-x-1/2"
              : "top-full mt-2 left-1/2 -translate-x-1/2"
          }`}
        >
          {content}
          {/* Arrow */}
          <div
            className={`absolute w-2 h-2 bg-popover border-border rotate-45 left-1/2 -translate-x-1/2 ${
              position === "top"
                ? "bottom-[-5px] border-r border-b"
                : "top-[-5px] border-l border-t"
            }`}
          />
        </div>
      )}
    </div>
  );
};
