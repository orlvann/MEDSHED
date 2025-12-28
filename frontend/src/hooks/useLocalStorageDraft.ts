import { useState, useCallback, useEffect } from "react";
import type { PreferenceWorkingPut } from "../types";

const DRAFT_KEY_PREFIX = "preferences_draft_";
const MAX_DRAFT_AGE_DAYS = 31;

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
  loadDraft: (doctorId: number, options?: { deleteIfExpired?: boolean }) => PreferenceWorkingPut | null;
  clearDraft: (doctorId: number) => void;
  isRestoredFromDraft: boolean;
  setRestoredFromDraft: (value: boolean) => void;
}

/**
 * Clean up old preference drafts from localStorage.
 * Removes drafts older than MAX_DRAFT_AGE_DAYS.
 */
function cleanupOldDrafts(): void {
  const now = new Date();
  const keysToRemove: string[] = [];

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(DRAFT_KEY_PREFIX)) continue;

    try {
      const stored = localStorage.getItem(key);
      if (!stored) continue;

      const parsed: DraftData = JSON.parse(stored);
      const savedAt = new Date(parsed.meta.savedAt);
      const ageInDays = (now.getTime() - savedAt.getTime()) / (1000 * 60 * 60 * 24);

      if (ageInDays > MAX_DRAFT_AGE_DAYS) {
        keysToRemove.push(key);
      }
    } catch {
      // Invalid data, remove it
      keysToRemove.push(key);
    }
  }

  for (const key of keysToRemove) {
    localStorage.removeItem(key);
  }
}

/**
 * Hook for managing localStorage draft of preferences.
 *
 * Functions accept doctorId as parameter to avoid timing issues
 * when opening/closing modals.
 *
 * Automatically cleans up drafts older than 31 days on mount.
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

  // Clean up old drafts on mount (once per session)
  useEffect(() => {
    cleanupOldDrafts();
  }, []);

  const getKey = useCallback(
    (doctorId: number) => `${DRAFT_KEY_PREFIX}${year}_${month}_${doctorId}`,
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
    (doctorId: number, options?: { deleteIfExpired?: boolean }): PreferenceWorkingPut | null => {
      if (!doctorId) return null;

      const key = getKey(doctorId);
      const stored = localStorage.getItem(key);
      if (stored) {
        try {
          const parsed: DraftData = JSON.parse(stored);

          // For doctor mode: delete draft if deadline has passed
          // For admin mode: keep draft even after deadline
          if (options?.deleteIfExpired && parsed.meta.deadline) {
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
