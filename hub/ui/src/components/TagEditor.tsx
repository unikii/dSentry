import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useLanguage } from "@/context/use-lang";
import { cn } from "@/lib/utils";

interface TagEditorProps {
  tags: string[];
  onSave: (tags: string[]) => void | Promise<void>;
  className?: string;
  compact?: boolean;
}

/**
 * Inline tag chips with delete buttons + a dashed "add" input.
 * Enter (or comma) commits the tag, Escape cancels.
 */
export function TagEditor({ tags, onSave, className, compact }: TagEditorProps) {
  const { t } = useLanguage();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async (next: string[]) => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(next);
    } finally {
      setSaving(false);
    }
  };

  const commit = async () => {
    const tag = value.trim().replace(/,+$/, "");
    setValue("");
    setEditing(false);
    if (!tag || tags.includes(tag)) return;
    await save([...tags, tag]);
  };

  const remove = async (tag: string) => {
    await save(tags.filter((t) => t !== tag));
  };

  return (
    <div
      className={cn("flex flex-wrap items-center gap-1.5", className)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {tags.map((tag) => (
        <Badge key={tag} variant="secondary" className={cn("group/tag gap-1 pr-1", compact && "text-[11px]")}>
          {tag}
          <button
            type="button"
            aria-label={t("tags.remove", { tag })}
            className="hover:text-destructive cursor-pointer rounded-full opacity-40 transition-opacity group-hover/tag:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              void remove(tag);
            }}
          >
            <X className="size-3" />
          </button>
        </Badge>
      ))}

      {editing ? (
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              void commit();
            }
            if (e.key === "Escape") {
              setValue("");
              setEditing(false);
            }
          }}
          placeholder={t("tags.placeholder")}
          className="border-muted-foreground/50 focus:border-ring h-6 w-20 rounded-md border border-dashed bg-transparent px-1.5 text-xs outline-none"
        />
      ) : (
        <button
          type="button"
          aria-label={t("tags.add")}
          className={cn(
            "border-muted-foreground/40 text-muted-foreground hover:border-ring hover:text-foreground inline-flex cursor-pointer items-center gap-1 rounded-md border border-dashed px-2 py-0.5 text-xs transition-colors",
            compact && "text-[11px]",
          )}
          onClick={(e) => {
            e.stopPropagation();
            setEditing(true);
          }}
        >
          <Plus className="size-3" />
          {t("tags.addButton")}
        </button>
      )}
    </div>
  );
}
