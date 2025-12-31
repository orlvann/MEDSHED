import { useState, useRef, useEffect } from "react";
import { ChevronDown, X, Check } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { InfoTooltip } from "./InfoTooltip";
import type { Doctor } from "../../types";

interface ColleagueSelectorProps {
  colleagues: Doctor[];
  selectedIds: number[];
  currentDoctorId: number;
  onChange: (selectedIds: number[]) => void;
  disabled?: boolean;
}

export const ColleagueSelector = ({
  colleagues,
  selectedIds,
  currentDoctorId,
  onChange,
  disabled = false,
}: ColleagueSelectorProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Filter out current doctor and apply search
  const availableColleagues = colleagues.filter(
    (c) =>
      c.id !== currentDoctorId &&
      (searchQuery === "" ||
        `${c.first_name} ${c.last_name}`
          .toLowerCase()
          .includes(searchQuery.toLowerCase()))
  );

  const selectedColleagues = colleagues.filter((c) => selectedIds.includes(c.id));

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setSearchQuery("");
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleColleague = (id: number) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((sid) => sid !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const removeColleague = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(selectedIds.filter((sid) => sid !== id));
  };

  const handleInputClick = () => {
    if (!disabled) {
      setIsOpen(true);
      inputRef.current?.focus();
    }
  };

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">Preferred colleagues on the same days</h3>
            <InfoTooltip
              content="Please select people you would like to work with"
            />
          </div>

          <div ref={dropdownRef} className="relative">
            {/* Dropdown trigger / selected items display */}
            <div
              onClick={handleInputClick}
              className={`min-h-[42px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 ${
                disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
              }`}
            >
              <div className="flex flex-wrap gap-1.5 items-center">
                {/* Selected colleague tags */}
                {selectedColleagues.map((colleague) => (
                  <span
                    key={colleague.id}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary/10 text-primary text-sm"
                  >
                    {colleague.first_name} {colleague.last_name}
                    {!disabled && (
                      <button
                        type="button"
                        onClick={(e) => removeColleague(colleague.id, e)}
                        className="hover:bg-primary/20 rounded-full p-0.5"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </span>
                ))}

                {/* Search input */}
                {!disabled && (
                  <input
                    ref={inputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onFocus={() => setIsOpen(true)}
                    placeholder={selectedIds.length === 0 ? "Select colleagues..." : ""}
                    className="flex-1 min-w-[120px] bg-transparent outline-none placeholder:text-muted-foreground"
                  />
                )}

                {/* Dropdown arrow */}
                <ChevronDown
                  className={`h-4 w-4 ml-auto text-muted-foreground transition-transform ${
                    isOpen ? "rotate-180" : ""
                  }`}
                />
              </div>
            </div>

            {/* Dropdown menu */}
            {isOpen && !disabled && (
              <div className="absolute z-50 w-full mt-1 rounded-md border border-input bg-background shadow-lg max-h-60 overflow-auto">
                {availableColleagues.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-muted-foreground">
                    {searchQuery ? "No colleagues found" : "No colleagues available"}
                  </div>
                ) : (
                  availableColleagues.map((colleague) => {
                    const isSelected = selectedIds.includes(colleague.id);
                    return (
                      <div
                        key={colleague.id}
                        onClick={() => toggleColleague(colleague.id)}
                        className={`flex items-center justify-between px-3 py-2 text-sm cursor-pointer hover:bg-muted ${
                          isSelected ? "bg-primary/5" : ""
                        }`}
                      >
                        <span>
                          {colleague.first_name} {colleague.last_name}
                        </span>
                        {isSelected && <Check className="h-4 w-4 text-primary" />}
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
