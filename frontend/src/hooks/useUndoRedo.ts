import { useState, useCallback, useRef } from "react";

interface UndoRedoOptions {
  maxHistory?: number;
}

interface UndoRedoState<T> {
  current: T;
  canUndo: boolean;
  canRedo: boolean;
  set: (value: T) => void;
  undo: () => void;
  redo: () => void;
  reset: (initialValue: T) => void;
}

/**
 * Hook for client-side undo/redo functionality.
 * Maintains a history stack of states with configurable max size.
 *
 * @param initialValue - Initial state value
 * @param options.maxHistory - Maximum history size (default: 50)
 */
export function useUndoRedo<T>(
  initialValue: T,
  options: UndoRedoOptions = {}
): UndoRedoState<T> {
  const { maxHistory = 50 } = options;

  // Use refs to store history to avoid stale closures
  const historyRef = useRef<T[]>([initialValue]);
  const indexRef = useRef(0);

  // Force re-render when history changes
  const [, forceUpdate] = useState({});

  const current = historyRef.current[indexRef.current];
  const canUndo = indexRef.current > 0;
  const canRedo = indexRef.current < historyRef.current.length - 1;

  const set = useCallback(
    (value: T) => {
      // Truncate future history if we're not at the end (after undo)
      historyRef.current = historyRef.current.slice(0, indexRef.current + 1);

      // Add new state
      historyRef.current.push(value);

      // Trim to max history if exceeded
      if (historyRef.current.length > maxHistory) {
        historyRef.current = historyRef.current.slice(-maxHistory);
        indexRef.current = historyRef.current.length - 1;
      } else {
        indexRef.current = historyRef.current.length - 1;
      }

      forceUpdate({});
    },
    [maxHistory]
  );

  const undo = useCallback(() => {
    if (indexRef.current > 0) {
      indexRef.current--;
      forceUpdate({});
    }
  }, []);

  const redo = useCallback(() => {
    if (indexRef.current < historyRef.current.length - 1) {
      indexRef.current++;
      forceUpdate({});
    }
  }, []);

  const reset = useCallback((newInitialValue: T) => {
    historyRef.current = [newInitialValue];
    indexRef.current = 0;
    forceUpdate({});
  }, []);

  return {
    current,
    canUndo,
    canRedo,
    set,
    undo,
    redo,
    reset,
  };
}
