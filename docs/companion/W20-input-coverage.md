# W20 — shared format matrix and local extraction

Checkpoint 2026-09-15, based on `4f2056fd`. This is the extraction foundation, not completion of video-frame understanding or all input acceptance.

The frontend pickers and backend readers share `web/src/lib/input_formats.json`, staged into `server/resources` in the desktop sidecar. This location also works with the isolated frontend build directory. Existing PDF/Word/HTML/image paths remain; code/data text, XLSX, PPTX and common video containers are added. Macro-enabled/legacy Office formats are not advertised. SVG/code are inert text in attachment and artifact preview paths.

New UTF-8 text readers reject binary input. XLSX/PPTX readers never evaluate formulas, run macros, fetch relationships, or extract archive members to disk. XML entities and alternate non-UTF-8 XML are rejected. Compressed input, member count, expanded size, XML member size, output length and cell/slide counts are bounded. Locators identify worksheet package path/cell and slide package path/paragraph. Formula values are explicitly unverified cached values, not recalculation. Slide diagrams/layout and spreadsheet styling are not visually understood by this path.

The ephemeral endpoint caps file reads at 30 MiB. New readers run off the request event loop. Error codes and capability disclosures have six-language resources. `/api/v1/input-formats` reports optional video-tool availability separately from format coverage.

Video metadata uses an optional local FFprobe, restricted to local file/pipe protocols and approved container demuxers, with a scrubbed environment, 20-second deadline and temporary-file cleanup. No model, network fetch, transcript or frame understanding is invoked. A real generated 2-second 64×48 H.264 fixture was probed successfully with duration, codec and dimensions; the response explicitly reports frames not extracted, transcript not generated and visual understanding/editing not run. FFmpeg is not newly bundled or automatically installed.

Evidence: 33 focused backend tests passed; 19 focused UI tests passed; TypeScript passed. Tests include malformed ZIP, XML entities including UTF-16, formula/cached-value distinction, inert source code, slide locators, video tool absence, local-only process arguments, capability matrix and structured API errors. No real user media, paid model or production data was used.

Remaining: sampled video frames with time locators, explicit transcript backend capability and end-to-end visual-input acceptance; richer PDF/Word source locators; runtime UI checks for the new picker/disclosures and full regression. This checkpoint does not claim those absent capabilities are complete.

## Video-frame extension (after `de4691c9`)

The ephemeral upload route now samples up to three still frames at approximately
0%, 50% and 90% of the video duration, when local FFprobe and FFmpeg are available.
Each frame is at most 512 pixels on its long edge and carries an explicit seek-time
source locator into both the main and delegated-expert image blocks. Sampling is
not full-motion understanding: unsampled content is not analyzed. Audio transcription
has no configured adapter and is reported unavailable, not fabricated. Editing is
not performed. Upload-time compression/model calls are bypassed for video so time
locators cannot be summarized away.

Decoder execution is bounded to one frame per process, one codec thread, an
eight-second deadline per frame, approved local container/protocol lists and a
scrubbed environment. Inputs with unavailable/nonfinite duration, duration over
24 hours, dimension over 8192 pixels or pixel area over 25 million are not decoded.
Partial results retain only completed frames; temporary files are cleaned on
success or timeout. FFmpeg's installed MOV demuxer reports external data references
and absolute-path aliases disabled by default; no flags enable either feature.
No tools or model weights are installed automatically.

The composer sends sampled frames through the existing image payload path and
discloses the number of frames, selected-model transmission and absence of audio/
full-motion analysis in all six languages. Aggregate messages are limited to nine
images/frames and 12 MiB of encoded image data. Text-only expert direct chat now
blocks visual attachments with an explicit main-conversation instruction instead
of silently discarding images. Main-conversation delegation continues to carry them.

Evidence: real generated two-second H.264 test video → three bounded PNGs with
locators → real OpenAI-compatible provider payload builder containing three native
image parts (no model/network call). The frontend integration test verifies file
selection → extraction response → send payload with those images/locators. This is
transport/decoding evidence, not a claim about a real model's answer quality.
46 focused backend/vision tests, 21 focused frontend tests, TypeScript and 232
frontend test files / 1,774 tests passed. The video suite, including two additional
timeout/partial-result tests, passed all eight tests; production build passed in
2.92 seconds (existing large-chunk warnings remain). Real UI picker/layout inspection remains pending the
locked Mac, alongside richer PDF/Word locators and W17's complete acceptance audit.
