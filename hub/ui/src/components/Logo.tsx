import { cn } from "@/lib/utils";

interface LogoMarkProps {
  className?: string;
}

/**
 * dSentry mark — a "d" formed by a stack of hard-disk platters, with the
 * ascender built as a little watchtower (see public/logo.png). Two
 * transparent PNGs keep the mark legible in both themes: navy on light
 * surfaces, white on dark ones.
 */
export function LogoMark({ className }: LogoMarkProps) {
  return (
    <>
      <img
        src="/logo-mark-navy.png"
        alt=""
        aria-hidden="true"
        draggable={false}
        className={cn(className, "dark:hidden")}
      />
      <img
        src="/logo-mark-white.png"
        alt=""
        aria-hidden="true"
        draggable={false}
        className={cn(className, "hidden dark:block")}
      />
    </>
  );
}
