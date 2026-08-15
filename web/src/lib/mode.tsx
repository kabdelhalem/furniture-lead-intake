import { createContext, useContext, useEffect, useState } from "react";

// Two audiences share the bench. Sales is the default: a salesperson wants a
// clean read of what was captured and the few things that need a decision.
// Engineering is the "god view" — confidence rails, thresholds, evidence,
// routing internals — kept a discreet toggle away.
export type Mode = "sales" | "engineering";

const KEY = "reviewbench.mode";

interface ModeApi {
  mode: Mode;
  setMode: (m: Mode) => void;
  isEng: boolean;
}

const ModeContext = createContext<ModeApi | null>(null);

function readStored(): Mode {
  try {
    return localStorage.getItem(KEY) === "engineering" ? "engineering" : "sales";
  } catch {
    return "sales";
  }
}

export function ModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<Mode>(readStored);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* private mode / storage disabled — fall back to in-memory only */
    }
  }, [mode]);

  const setMode = (m: Mode) => setModeState(m);

  return (
    <ModeContext.Provider value={{ mode, setMode, isEng: mode === "engineering" }}>
      {children}
    </ModeContext.Provider>
  );
}

export function useMode(): ModeApi {
  const ctx = useContext(ModeContext);
  if (!ctx) throw new Error("useMode must be used inside ModeProvider");
  return ctx;
}
