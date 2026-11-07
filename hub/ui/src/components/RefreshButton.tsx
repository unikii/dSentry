import { useCallback, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface RefreshButtonProps {
  /** Silent reload, e.g. `() => reload(true)` from `usePagedList`. */
  onRefresh: () => void | Promise<unknown>;
  disabled?: boolean;
  label?: string;
}

/** Manual refresh button with a spinning state while the reload is in flight. */
export function RefreshButton({ onRefresh, disabled, label = "Refresh" }: RefreshButtonProps) {
  const [refreshing, setRefreshing] = useState(false);
  const onClick = useCallback(() => {
    setRefreshing(true);
    void Promise.resolve(onRefresh()).finally(() => setRefreshing(false));
  }, [onRefresh]);
  return (
    <Button
      variant="outline"
      size="icon"
      onClick={onClick}
      disabled={disabled || refreshing}
      title={label}
      aria-label={label}
    >
      <RefreshCw className={refreshing ? "size-4 animate-spin" : "size-4"} />
    </Button>
  );
}
