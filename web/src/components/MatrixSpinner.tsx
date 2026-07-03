/**
 * MatrixSpinner — the single "something is working" loader used across every
 * agent-waiting moment (the phase line, running tool steps, a spawn thinking).
 *
 * A ring of dots that pulse in sequence (a chase), reading as a dot-matrix loader
 * that fits the terminal/daemon aesthetic. Original SVG + CSS implementation of a
 * generic loader pattern; the dot-matrix look was inspired by sv-matrix's loaders
 * (MIT). Uses `currentColor`, so callers tint it with `text-*` classes exactly like
 * the lucide icons it replaces. Honours prefers-reduced-motion (handled in CSS).
 */
interface Props {
  /** Pixel size of the square icon (default 14, matching the icons it replaces). */
  size?: number;
  /** Number of dots around the ring. */
  count?: number;
  className?: string;
  label?: string;
}

export default function MatrixSpinner({
  size = 14,
  count = 8,
  className = '',
  label = 'Working',
}: Props) {
  const center = 12; // viewBox center (0 0 24 24)
  const radius = 8; // ring radius
  const dots = Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * 2 * Math.PI - Math.PI / 2;
    return {
      cx: center + radius * Math.cos(angle),
      cy: center + radius * Math.sin(angle),
      delay: i / count, // staggered over the 1s cycle → a chase around the ring
    };
  });

  return (
    <svg
      className={`matrix-spinner ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      role="img"
      aria-label={label}
    >
      {dots.map((d, i) => (
        <circle
          key={i}
          className="matrix-spinner__dot"
          cx={d.cx}
          cy={d.cy}
          r={2}
          style={{ animationDelay: `${d.delay}s` }}
        />
      ))}
    </svg>
  );
}
