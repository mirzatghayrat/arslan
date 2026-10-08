/**
 * The mascot on an asking surface (0.1.55): Arslan's black-and-white head, rigid
 * (Island rule 2026-10-03), mouth = the amber "!" while something waits for you.
 * Light theme: the head sits in a small black circle; dark theme: an amber halo.
 * The head's own black/white/grey are brand art, not theme colours.
 */
const HEAD = "M286 517L283 287C283 231 320 208 358 237L494 332Q626 280 758 332L894 237C932 208 969 231 969 287L966 517C966 562 982 603 963 651C944 694 909 731 880 777L811 890C758 974 698 1006 626 1006C554 1006 494 974 441 890L372 777C343 731 308 694 289 651C270 603 286 562 286 517Z";
const EARS = "M310 496L307 286Q307 236 349 259L465 343Q376 404 310 496ZM942 496L945 286Q945 236 903 259L787 343Q876 404 942 496Z";
const EYES = "M386 518C478 501 558 551 552 650C449 654 387 604 386 518ZM866 518C774 501 694 551 700 650C803 654 865 604 866 518Z";

export function MascotHead({ size = 22, mouth = "ask" }: { size?: number; mouth?: "ask" | "idle" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 1254 1254" aria-hidden="true" className="relative">
      <g transform="translate(-130 -170) scale(1.21)">
        <path fill="white" d={HEAD} />
        <path fill="gray" fillOpacity={0.75} d={EARS} />
        <path fill="black" d={EYES} />
        {mouth === "ask" ? <>
          <path fill="none" stroke="var(--ask)" strokeWidth={40} strokeLinecap="round" d="M626 700V830" />
          <circle fill="var(--ask)" cx={626} cy={905} r={32} />
        </> : <>
          <path fill="none" stroke="black" strokeWidth={10} strokeLinecap="round" d="M626 696L495 813M626 696L757 813M626 696V893" />
          <g fill="black"><circle cx={626} cy={696} r={29} /><circle cx={495} cy={813} r={25} /><circle cx={757} cy={813} r={25} /><circle cx={626} cy={893} r={30} /></g>
        </>}
      </g>
    </svg>
  );
}

export function AskMark({ size = 34, mouth = "ask" }: { size?: number; mouth?: "ask" | "idle" }) {
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center rounded-full bg-mark"
      style={{ width: size, height: size }}>
      <span aria-hidden="true" className="pointer-events-none absolute -inset-3 hidden rounded-full dark:block"
        style={{ background: "radial-gradient(circle, var(--ask-soft) 0%, transparent 62%)" }} />
      <MascotHead size={Math.round(size * 0.65)} mouth={mouth} />
    </span>
  );
}
