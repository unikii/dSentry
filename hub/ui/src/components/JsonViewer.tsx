import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useLanguage } from "@/context/use-lang";

type JsonNodeProps = {
  keyName?: string;
  value: unknown;
  depth: number;
  path: string;
};

function JsonNode({ keyName, value, depth, path }: JsonNodeProps) {
  const { t } = useLanguage();
  const [collapsed, setCollapsed] = useState(depth > 2);

  // smartctl output is normally shallow; cap pathological/malicious nesting.
  if (depth > 24) {
    return (
      <div className="text-muted-foreground font-mono text-xs" style={{ paddingLeft: depth * 16 }}>
        …
      </div>
    );
  }

  if (value === null) {
    return (
      <div className="flex items-start gap-1 font-mono text-xs leading-relaxed" style={{ paddingLeft: depth * 16 }}>
        {keyName !== undefined && <span className="text-info shrink-0">"{keyName}": </span>}
        <span className="text-nvme">null</span>
      </div>
    );
  }

  if (typeof value === "boolean") {
    return (
      <div className="flex items-start gap-1 font-mono text-xs leading-relaxed" style={{ paddingLeft: depth * 16 }}>
        {keyName !== undefined && <span className="text-info shrink-0">"{keyName}": </span>}
        <span className="text-nvme">{String(value)}</span>
      </div>
    );
  }

  if (typeof value === "number") {
    return (
      <div className="flex items-start gap-1 font-mono text-xs leading-relaxed" style={{ paddingLeft: depth * 16 }}>
        {keyName !== undefined && <span className="text-info shrink-0">"{keyName}": </span>}
        <span className="text-warning">{value}</span>
      </div>
    );
  }

  if (typeof value === "string") {
    const display = value.length > 200 ? `${value.slice(0, 200)}…` : value;
    return (
      <div className="flex items-start gap-1 font-mono text-xs leading-relaxed" style={{ paddingLeft: depth * 16 }}>
        {keyName !== undefined && <span className="text-info shrink-0">"{keyName}": </span>}
        <span className="text-success break-all">"{display}"</span>
      </div>
    );
  }

  if (Array.isArray(value)) {
    const entries = value as unknown[];
    const bracket = collapsed
      ? t("json.items", { count: entries.length })
      : "[";
    const endBracket = collapsed ? "" : "]";

    return (
      <div>
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="hover:text-foreground text-muted-foreground inline-flex cursor-pointer items-center gap-0.5 font-mono text-xs leading-relaxed"
          style={{ paddingLeft: depth * 16 }}
        >
          {collapsed ? <ChevronRight className="size-3.5 shrink-0" /> : <ChevronDown className="size-3.5 shrink-0" />}
          {keyName !== undefined && <span className="text-info">"{keyName}": </span>}
          <span>{bracket}</span>
        </button>
        {!collapsed &&
          entries.map((item, i) => (
            <JsonNode
              key={`${path}[${i}]`}
              keyName={undefined}
              value={item}
              depth={depth + 1}
              path={`${path}[${i}]`}
            />
          ))}
        {!collapsed && (
          <div className="font-mono text-xs" style={{ paddingLeft: depth * 16 }}>
            {endBracket}
          </div>
        )}
      </div>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const bracket = collapsed ? t("json.keys", { count: entries.length }) : "{";
    const endBracket = collapsed ? "" : "}";

    return (
      <div>
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="hover:text-foreground text-muted-foreground inline-flex cursor-pointer items-center gap-0.5 font-mono text-xs leading-relaxed"
          style={{ paddingLeft: depth * 16 }}
        >
          {collapsed ? <ChevronRight className="size-3.5 shrink-0" /> : <ChevronDown className="size-3.5 shrink-0" />}
          {keyName !== undefined && <span className="text-info">"{keyName}": </span>}
          <span>{bracket}</span>
        </button>
        {!collapsed &&
          entries.map(([k, v]) => (
            <JsonNode
              key={`${path}.${k}`}
              keyName={k}
              value={v}
              depth={depth + 1}
              path={`${path}.${k}`}
            />
          ))}
        {!collapsed && (
          <div className="font-mono text-xs" style={{ paddingLeft: depth * 16 }}>
            {endBracket}
          </div>
        )}
      </div>
    );
  }

  return null;
}

export function JsonViewer({ data }: { data: unknown }) {
  return (
    <div className="scrollbar-thin bg-secondary/35 mt-2 max-h-96 overflow-auto rounded-xl border border-border/55 p-4">
      <JsonNode value={data} depth={0} path="$" />
    </div>
  );
}
