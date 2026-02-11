import { useState, useRef, useLayoutEffect } from "react";
import { Info } from "lucide-react";

interface InfoTooltipProps {
  content: string | React.ReactNode;
  className?: string;
}

export const InfoTooltip = ({ content, className = "" }: InfoTooltipProps) => {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const arrowRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLButtonElement>(null);

  // Position synchronously before browser paint to prevent flash
  useLayoutEffect(() => {
    const tooltip = tooltipRef.current;
    const icon = iconRef.current;
    const arrow = arrowRef.current;
    if (!isVisible || !tooltip || !icon || !arrow) return;

    // Hide tooltip temporarily so it doesn't inflate viewport width
    tooltip.style.visibility = "hidden";
    tooltip.style.left = "0px";
    tooltip.style.top = "0px";

    const iconRect = icon.getBoundingClientRect();
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;
    const vw =
      window.visualViewport?.width ?? document.documentElement.clientWidth;
    const vh =
      window.visualViewport?.height ?? document.documentElement.clientHeight;
    const padding = 12;
    const gap = 8;

    // Vertical: prefer above, fall back to below
    const spaceAbove = iconRect.top;
    const spaceBelow = vh - iconRect.bottom;
    const showBelow = spaceAbove < tooltipHeight + gap && spaceBelow > spaceAbove;

    let top: number;
    if (showBelow) {
      top = iconRect.bottom + gap;
      arrow.style.top = "-5px";
      arrow.style.bottom = "auto";
      arrow.className =
        "absolute w-2 h-2 bg-popover border-border rotate-45 -translate-x-1/2 border-l border-t";
    } else {
      top = iconRect.top - tooltipHeight - gap;
      arrow.style.bottom = "-5px";
      arrow.style.top = "auto";
      arrow.className =
        "absolute w-2 h-2 bg-popover border-border rotate-45 -translate-x-1/2 border-r border-b";
    }

    // Horizontal: center tooltip on icon, then clamp to viewport
    const iconCenter = iconRect.left + iconRect.width / 2;
    let left = iconCenter - tooltipWidth / 2;

    if (left < padding) left = padding;
    if (left + tooltipWidth > vw - padding)
      left = vw - padding - tooltipWidth;

    tooltip.style.top = `${top}px`;
    tooltip.style.left = `${left}px`;
    tooltip.style.visibility = "visible";

    // Arrow points at icon center
    const arrowPos = Math.max(
      8,
      Math.min(iconCenter - left, tooltipWidth - 8)
    );
    arrow.style.left = `${arrowPos}px`;
  }, [isVisible]);

  return (
    <div className={`relative inline-flex items-center ${className}`}>
      <button
        ref={iconRef}
        type="button"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onClick={() => setIsVisible(!isVisible)}
        className="inline-flex items-center justify-center w-5 h-5 text-muted-foreground hover:text-foreground transition-colors rounded-full hover:bg-gray-100"
        aria-label="More information"
      >
        <Info className="w-4 h-4" />
      </button>

      {isVisible && (
        <div
          ref={tooltipRef}
          style={{ visibility: "hidden" }}
          className="fixed z-50 px-3 py-2.5 text-[13px] leading-relaxed font-normal bg-popover text-popover-foreground border border-border rounded-lg shadow-lg w-[min(280px,calc(100vw-2rem))] whitespace-normal"
        >
          {content}
          <div
            ref={arrowRef}
            className="absolute w-2 h-2 bg-popover border-border rotate-45 -translate-x-1/2"
          />
        </div>
      )}
    </div>
  );
};
