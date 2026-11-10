import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import type { SubStatus } from "../lib/subTree";

/** SUB5d (the approved mock): a sub-session's status shown by motion, not words. Running is a small spinning amber
 *  ring, waiting on you a slowly breathing blue dot, done a still green check. The word is the tooltip and the label;
 *  with reduced motion asked for, nothing moves. */
export default function SubStatusIcon({ status, size = 12 }: { status: SubStatus; size?: number }) {
  const { t } = useTranslation();
  const still = usePrefersReducedMotion();
  const label = t(`subTree.status.${status}`);
  return <span role="img" aria-label={label} title={label} data-status={status} data-motion={still ? "still" : "moving"}
    className="inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
    {status === "running" && <span aria-hidden className={`block rounded-full border-[1.5px] border-warning/30 border-t-warning ${still ? "" : "animate-spin"}`}
      style={{ width: size - 2, height: size - 2, animationDuration: "1.1s" }} />}
    {status === "waiting" && <span aria-hidden className={`block rounded-full bg-info-strong ${still ? "" : "animate-pulse"}`}
      style={{ width: size / 2, height: size / 2, animationDuration: "2.4s" }} />}
    {status === "done" && <Check aria-hidden size={size} strokeWidth={2.5} className="text-success" />}
  </span>;
}
