export function DriveGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className={className} aria-hidden>
      <rect x="2.75" y="5.25" width="18.5" height="13.5" rx="2.4" strokeWidth="1.35" />
      <circle cx="16.9" cy="12" r="2.65" strokeWidth="1.35" />
      <circle cx="16.9" cy="12" r="0.7" fill="currentColor" stroke="none" />
      <path d="M6.4 9h5.2M6.4 12h4M6.4 15h5.2" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M2.9 17.9h18.2" strokeWidth="1.1" strokeLinecap="round" opacity="0.35" />
    </svg>
  );
}
