# W20 — shared format matrix and local extraction

Checkpoint 2026-09-15, based on `4f2056fd`. This is the extraction foundation, not completion of video-frame understanding or all input acceptance.

The frontend pickers and backend readers share `web/src/lib/input_formats.json`, staged into `server/resources` in the desktop sidecar. This location also works with the isolated frontend build directory. Existing PDF/Word/HTML/image paths remain; code/data text, XLSX, PPTX and common video containers are added. Macro-enabled/legacy Office formats are not advertised. SVG/code are inert text in attachment and artifact preview paths.

New UTF-8 text readers reject binary input. XLSX/PPTX readers never evaluate formulas, run macros, fetch relationships, or extract archive members to disk. XML entities and alternate non-UTF-8 XML are rejected. Compressed input, member count, expanded size, XML member size, output length and cell/slide counts are bounded. Locators identify worksheet package path/cell and slide package path/paragraph. Formula values are explicitly unverified cached values, not recalculation. Slide diagrams/layout and spreadsheet styling are not visually understood by this path.

The ephemeral endpoint caps file reads at 30 MiB. New readers run off the request event loop. Error codes and capability disclosures have six-language resources. `/api/v1/input-formats` reports optional video-tool availability separately from format coverage.

Video metadata uses an optional local FFprobe, restricted to local file/pipe protocols and approved container demuxers, with a scrubbed environment, 20-second deadline and temporary-file cleanup. No model, network fetch, transcript or frame understanding is invoked. A real generated 2-second 64×48 H.264 fixture was probed successfully with duration, codec and dimensions; the response explicitly reports frames not extracted, transcript not generated and visual understanding/editing not run. FFmpeg is not newly bundled or automatically installed.

Evidence: 33 focused backend tests passed; 19 focused UI tests passed; TypeScript passed. Tests include malformed ZIP, XML entities including UTF-16, formula/cached-value distinction, inert source code, slide locators, video tool absence, local-only process arguments, capability matrix and structured API errors. No real user media, paid model or production data was used.

Remaining: sampled video frames with time locators, explicit transcript backend capability and end-to-end visual-input acceptance; richer PDF/Word source locators; runtime UI checks for the new picker/disclosures and full regression. This checkpoint does not claim those absent capabilities are complete.
