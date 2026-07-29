import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// The schematic scenes are full-bleed vector art on a near-black plate; banding
// shows up fast at low bitrates, so bias the encoder toward quality.
Config.setCrf(17);
Config.setChromiumOpenGlRenderer('angle');

// The film has no narration or score. Left on, Remotion writes a silent AAC
// track at its default 320 kbps — 2.4 MB of encoded silence on a 58-second
// render, 28% of the output. Set here rather than on the render command so
// every render drops it, not just `npm run build`.
Config.setMuted(true);

/**
 * Inline the vendored `.woff2` faces as data URIs instead of serving them from
 * `public/`. Fonts fetched over the render-time static server were timing out
 * mid-render — `delayRender()` would sit on a font request that never came
 * back, and the run died a thousand frames in. A data URI resolves inside the
 * page with no request at all, so the failure mode is gone rather than made
 * less likely.
 */
Config.overrideWebpackConfig((current) => ({
  ...current,
  module: {
    ...current.module,
    rules: [
      ...(current.module?.rules ?? []),
      {test: /\.woff2$/, type: 'asset/inline'},
    ],
  },
}));

export {};
