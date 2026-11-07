import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLanguage } from "@/context/use-lang";
import { PAGE_SIZE_OPTIONS } from "@/lib/constants";

interface PaginationProps {
  page: number;
  pages: number;
  total: number;
  limit: number;
  onPage: (page: number) => void;
  onLimit: (limit: number) => void;
}

function pageNumbers(current: number, pages: number): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const out: (number | "…")[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(pages - 1, current + 1);
  if (start > 2) out.push("…");
  for (let i = start; i <= end; i++) out.push(i);
  if (end < pages - 1) out.push("…");
  out.push(pages);
  return out;
}

export function Pagination({ page, pages, total, limit, onPage, onLimit }: PaginationProps) {
  const { t } = useLanguage();
  if (total === 0) return null;

  return (
    <div className="border-border/55 bg-card/25 flex flex-col items-center justify-between gap-3 rounded-2xl border px-3 py-2.5 backdrop-blur-sm sm:flex-row sm:px-4">
      <p className="text-muted-foreground text-[11px]">
        {t("pagination.page")} <span className="text-foreground font-mono font-medium">{page}</span> {t("pagination.of")}{" "}
        <span className="text-foreground font-mono font-medium">{Math.max(pages, 1)}</span>
        <span className="text-border mx-2">·</span>
        <span className="text-foreground font-mono font-medium">{total}</span> {t("pagination.total")}
      </p>

      <div className="flex items-center gap-2">
        <Select value={String(limit)} onValueChange={(v) => onLimit(Number(v))}>
          <SelectTrigger size="sm" className="min-w-24 border-border/60 bg-card/40" aria-label={t("pagination.itemsPerPage")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZE_OPTIONS.map((n) => (
              <SelectItem key={n} value={String(n)}>
                {t("pagination.perPage", { n })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label={t("pagination.prev")}>
            <ChevronLeft className="size-4" />
          </Button>
          <div className="hidden items-center gap-1 sm:flex">
            {pageNumbers(page, pages).map((p, i) =>
              p === "…" ? (
                <span key={`e${i}`} className="text-muted-foreground/70 px-1 font-mono text-xs">
                  …
                </span>
              ) : (
                <Button
                  key={p}
                  variant={p === page ? "default" : "outline"}
                  size="icon-sm"
                  onClick={() => onPage(p)}
                  className="min-w-8 font-mono text-[11px]"
                >
                  {p}
                </Button>
              ),
            )}
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
            aria-label={t("pagination.next")}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
