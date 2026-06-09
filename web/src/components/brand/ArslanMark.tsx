// Arslan cat-head mark — a clean monochrome re-creation of the logo's head + node-branch
// motif ("one becomes many"). Monochrome (currentColor) so it inherits the brand accent;
// transparent background, scales to any size. No wordmark (too tight for a nav bar).

export default function ArslanMark({
  className = "h-7 w-7 text-brand",
  title = "Arslan",
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 64 64"
      fill="none"
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      {/* ears */}
      <path d="M14 22 L20 6 L30 20 Z" fill="currentColor" />
      <path d="M50 22 L44 6 L34 20 Z" fill="currentColor" />
      {/* head */}
      <circle cx="32" cy="34" r="23" stroke="currentColor" strokeWidth="3" />
      {/* eyes (almond) */}
      <path d="M20 30 Q24 26 28 30 Q24 33 20 30 Z" fill="currentColor" />
      <path d="M36 30 Q40 26 44 30 Q40 33 36 30 Z" fill="currentColor" />
      {/* node-branch motif (the logo's nose): one hub -> three nodes */}
      <g stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="32" y1="40" x2="23" y2="50" />
        <line x1="32" y1="40" x2="32" y2="52" />
        <line x1="32" y1="40" x2="41" y2="50" />
      </g>
      <g fill="currentColor">
        <circle cx="32" cy="40" r="4" />
        <circle cx="23" cy="50" r="3" />
        <circle cx="32" cy="52" r="3" />
        <circle cx="41" cy="50" r="3" />
      </g>
    </svg>
  );
}
