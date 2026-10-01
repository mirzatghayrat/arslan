/** Tiny bar sparkline (usage-by-day). Moved out of the deleted Diagnostics catalog in 0.1.48. */
export function Sparkline({ points }: { points: number[] }) {
  if (points.length === 0) return <span className="cat-spark cat-spark--empty">—</span>;
  const max = Math.max(...points, 10);
  return (
    <span className="cat-spark" aria-hidden="true">
      {points.map((p, i) => (
        <span
          key={i}
          className="cat-spark__bar"
          style={{ height: `${Math.max(8, Math.round((p / max) * 100))}%` }}
        />
      ))}
    </span>
  );
}
