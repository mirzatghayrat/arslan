// Animated Arslan mark (glossy SVG recreation of the brand mark) — used only on
// the orchestrator greeting. Idle: gentle breathe + occasional head-tilt
// ("looking around"); periodic blink (eyes squash). Honours reduced-motion.
// Static raster (arslan-mark.png) is still used everywhere else.

interface Props {
  size?: number;
  className?: string;
}

export function ArslanMarkAnimated({ size = 48, className = "" }: Props) {
  return (
    <span className={`am-wrap ${className}`} style={{ display: "inline-block", width: size, height: size, lineHeight: 0 }} aria-hidden="true">
      <style>{`
        @keyframes am-idle {
          0%,100% { transform: rotate(0deg) scale(1); }
          22% { transform: rotate(-3.5deg) scale(1.01); }
          50% { transform: rotate(0deg) scale(1.02); }
          78% { transform: rotate(3.5deg) scale(1.01); }
        }
        @keyframes am-blink {
          0%,90%,100% { transform: scaleY(1); }
          94% { transform: scaleY(0.08); }
          97% { transform: scaleY(1); }
        }
        @keyframes am-ear {
          0%,86%,100% { transform: rotate(0deg); }
          90% { transform: rotate(-5deg); }
          94% { transform: rotate(0deg); }
        }
        .am-svg { animation: am-idle 7.5s ease-in-out infinite; transform-origin: 50% 64%; will-change: transform; }
        .am-eyes { animation: am-blink 4.6s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
        .am-earL { animation: am-ear 9s ease-in-out infinite; transform-origin: 32px 30px; transform-box: view-box; }
        .am-earR { animation: am-ear 9s ease-in-out infinite 1.3s; transform-origin: 68px 30px; transform-box: view-box; }
        @media (prefers-reduced-motion: reduce) {
          .am-svg, .am-eyes, .am-earL, .am-earR { animation: none; }
        }
      `}</style>
      <svg className="am-svg" viewBox="0 0 100 100" width={size} height={size}>
        <defs>
          <linearGradient id="am-ear" x1="0" y1="0" x2="0.3" y2="1"><stop offset="0" stopColor="#FFB45A"/><stop offset="1" stopColor="#EC7B12"/></linearGradient>
          <radialGradient id="am-face" cx="0.42" cy="0.34" r="0.8"><stop offset="0" stopColor="#FFFBF4"/><stop offset="0.7" stopColor="#FCEFE0"/><stop offset="1" stopColor="#F1DDC8"/></radialGradient>
          <radialGradient id="am-node" cx="0.34" cy="0.28" r="0.85"><stop offset="0" stopColor="#FFD584"/><stop offset="0.5" stopColor="#F89A2C"/><stop offset="1" stopColor="#E5780F"/></radialGradient>
        </defs>
        <path className="am-earL" d="M27 44 C21 27 21 14 25 11 C29 8 33 13 48 29 C41 41 32 44 27 44 Z" fill="url(#am-ear)"/>
        <path className="am-earR" d="M73 44 C79 27 79 14 75 11 C71 8 67 13 52 29 C59 41 68 44 73 44 Z" fill="url(#am-ear)"/>
        <ellipse cx="50" cy="89" rx="28" ry="5" fill="#E6C6A4" opacity="0.4"/>
        <circle cx="50" cy="55" r="34" fill="url(#am-face)" stroke="#EBD8C3" strokeWidth="0.7"/>
        <path d="M33 47 Q39 36 49 41" fill="none" stroke="#FFFDF8" strokeWidth="1.6" strokeLinecap="round" opacity="0.85"/>
        <path d="M67 47 Q61 36 51 41" fill="none" stroke="#FFFDF8" strokeWidth="1.6" strokeLinecap="round" opacity="0.85"/>
        <path d="M43 56 Q50 53 57 56 Q61 65 56 75 Q50 81 44 75 Q39 65 43 56 Z" fill="none" stroke="#FFFDF8" strokeWidth="1.5" opacity="0.8"/>
        <g className="am-eyes">
          <path d="M48 41 Q36 41 34 53 Q43 51 48 42 Z" fill="url(#am-ear)"/>
          <path d="M52 41 Q64 41 66 53 Q57 51 52 42 Z" fill="url(#am-ear)"/>
        </g>
        <path d="M50 52.5 L50 58" fill="none" stroke="#F08C24" strokeWidth="3" strokeLinecap="round"/>
        <path d="M50 61 L41 70" fill="none" stroke="#F08C24" strokeWidth="3" strokeLinecap="round"/>
        <path d="M50 61 L59 70" fill="none" stroke="#F08C24" strokeWidth="3" strokeLinecap="round"/>
        <circle cx="50" cy="50" r="3.2" fill="url(#am-node)"/>
        <circle cx="50" cy="61" r="4.3" fill="url(#am-node)"/>
        <circle cx="41" cy="71" r="3.2" fill="url(#am-node)"/>
        <circle cx="59" cy="71" r="3.2" fill="url(#am-node)"/>
        <circle cx="48.7" cy="59.6" r="1.2" fill="#fff" opacity="0.8"/>
        <ellipse cx="68" cy="36" rx="2.2" ry="2.2" fill="#fff" opacity="0.55"/>
      </svg>
    </span>
  );
}
