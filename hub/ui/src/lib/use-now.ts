import { useEffect, useState } from "react";

/**
 * A Date.now() value that re-renders the caller on a fixed cadence, so
 * relative computations (offline badges, "x minutes ago") don't go stale
 * while the page sits open.
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
