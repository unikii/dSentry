import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ButtonSize, ButtonVariant } from "@/components/ui/button-variants";
import { useLanguage } from "@/context/use-lang";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  text: string;
  label?: string;
  copiedLabel?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}

export function CopyButton({ text, label, copiedLabel, variant = "outline", size = "sm", className }: CopyButtonProps) {
  const { t } = useLanguage();
  const doneLabel = copiedLabel ?? t("common.copied");
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // clipboard API may be unavailable (non-secure context) — fallback
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Button type="button" variant={variant} size={size} onClick={copy} className={cn(copied && "text-success", className)}>
      {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      {label ? (copied ? doneLabel : label) : null}
      {!label && copied ? <span className="text-xs">{doneLabel}</span> : null}
    </Button>
  );
}
