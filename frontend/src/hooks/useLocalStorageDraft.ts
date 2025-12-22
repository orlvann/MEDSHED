import { useState, useCallback } from "react";
import type { PreferenceWorkingPut } from "../types";

interface DraftMeta {
  savedAt: string;
  deadline: string | null;
}

interface DraftData {
  data: PreferenceWorkingPut;
  meta: DraftMeta;
}

interface LocalStorageDraftResult {
  saveDraft: (doctorId: number, data: PreferenceWorkingPut) => void;
  loadDraft: (doctorId: number) => PreferenceWorkingPut | null;
  clearDraft: (doctorId: number) => void;
  isRestoredFromDraft: boolean;
  setRestoredFromDraft: (value: boolean) => void;
}

/**
 * Hook for managing localStorage draft of preferences.
 * Automatically cleans up drafts when deadline passes.
 *
 * Functions accept doctorId as parameter to avoid timing issues
 * when opening/closing modals.
 *
 * @param year - Year of the preference period
 * @param month - Month of the preference period
 * @param deadline - Deadline ISO string (null if no deadline set)
 */
export function useLocalStorageDraft(
  year: number,
  month: number,
  deadline: string | null
): LocalStorageDraftResult {
  const [isRestoredFromDraft, setRestoredFromDraft] = useState(false);

  const getKey = useCallback(
    (doctorId: number) => `preferences_draft_${year}_${month}_${doctorId}`,
    [year, month]
  );

  const saveDraft = useCallback(
    (doctorId: number, data: PreferenceWorkingPut) => {
      if (!doctorId) return;

      const key = getKey(doctorId);
      const draftData: DraftData = {
        data,
        meta: {
          savedAt: new Date().toISOString(),
          deadline,
        },
      };
      localStorage.setItem(key, JSON.stringify(draftData));
    },
    [getKey, deadline]
  );

  const loadDraft = useCallback(
    (doctorId: number): PreferenceWorkingPut | null => {
      if (!doctorId) return null;

      const key = getKey(doctorId);
      const stored = localStorage.getItem(key);
      if (stored) {
        try {
          const parsed: DraftData = JSON.parse(stored);

          // Check if deadline has passed - auto-delete
          if (parsed.meta.deadline) {
            const deadlineDate = new Date(parsed.meta.deadline);
            if (deadlineDate < new Date()) {
              localStorage.removeItem(key);
              return null;
            }
          }

          return parsed.data;
        } catch {
          localStorage.removeItem(key);
          return null;
        }
      }
      return null;
    },
    [getKey]
  );

  const clearDraft = useCallback(
    (doctorId: number) => {
      if (!doctorId) return;
      const key = getKey(doctorId);
      localStorage.removeItem(key);
      setRestoredFromDraft(false);
    },
    [getKey]
  );

  return {
    saveDraft,
    loadDraft,
    clearDraft,
    isRestoredFromDraft,
    setRestoredFromDraft,
  };
}
