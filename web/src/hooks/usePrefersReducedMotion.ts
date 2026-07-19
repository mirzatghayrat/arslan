import { useEffect, useState } from "react";

/** Whether the viewer asked for reduced motion.
 *
 * The repo already honours this in CSS (index.css) and inline in WorkingPulse, but the
 * brain graph never did: `brainPulse` runs an infinite glow loop and every node carries
 * transform/opacity transitions, none of them guarded. This hook is the JS-side answer
 * for animation that lives in inline styles, where a CSS media query cannot reach.
 *
 * It SUBSCRIBES rather than reading once, because the setting can change while the page
 * is open and a graph that keeps pulsing after the user turns motion off is exactly the
 * complaint the setting exists to fix.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() =>
    typeof window !== "undefined"
      ? (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false)
      : false,
  );

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    // addEventListener is not available on MediaQueryList in older Safari
    if (mq.addEventListener) {
      mq.addEventListener("change", on);
      return () => mq.removeEventListener("change", on);
    }
    mq.addListener(on);
    return () => mq.removeListener(on);
  }, []);

  return reduced;
}
