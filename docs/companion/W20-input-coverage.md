# W20 — shared format matrix and local extraction

## Attachment delivery fidelity — 2026-09-19, after `3a5cab09`

Both main and direct-expert composers now carry extraction limitations into
model-bound text, not just pre-send chips. Truncated excerpts retain their exact
content with a localized partial-source notice. Empty/whitespace-only extraction
and unprepared images carry an explicit unavailable-content notice and source
name. Successfully prepared image-only inputs keep their existing real image
payload path without a false empty-text warning. Complete text remains byte-for-byte
unchanged; expert refinement still includes the original deliverable.

Sent-message attachment echoes retain the same limitation in all six languages.
Failed image preparation renders a labeled file chip, not a thumbnail suggesting
successful transmission. Notices wrap independently of ellipsized source names.
This display metadata remains session-only, matching the existing attachment
echo contract; it does not retrofit historical messages or recover missing text.

Validation: 249 frontend test files / 1,930 tests passed in 24.22 seconds,
including main/direct delivery, failed-image/empty/partial helper cases, successful
visual input, refinement preservation and six-language parity. TypeScript and
production build passed (3.16 seconds; existing large-chunk warnings). The first
full run caught the expected locale-key baseline increase from 1,517 to 1,520;
the baseline was updated only after all six locales gained the three notices.
JUnit: `/tmp/arslan-attachment-fidelity-regression.xml`, SHA-256
`d21d51b9c16825912d9ab36aa43325eb5deddf3ebedb45db1239497233c1816b`.

This is source/frontend validation. The temporary native candidate still predates
this change; packaged visual acceptance and real selected-model quality remain
open. No account, model call, production data, installed app or publication was
used or changed.

### Subsequent packaged desktop validation

The temporary candidate was refreshed from `dd150e9a` frontend assets. Native
Chinese/dark normal-width inspection used only the synthetic profile
`/private/tmp/arslan-native-restore-ui-m1tgzvbv` and generated fixtures under
`/tmp/arslan-attachment-*-fixture.*`. A 600-line source file really hit the
12,000-character extraction cap; its sent chip retained the partial-source
notice. A whitespace-only text file retained the no-readable-text notice, and
a deliberately invalid PNG became a labeled unavailable-image chip after send,
not a misleading successful thumbnail. Screenshot and accessibility readings
confirmed the notices without overlapping the file name or message text.

This test also exposed an unrelated legacy-provider fallback: a profile with
no selected provider/model but a synthetic restored key attempted the default
OpenAI endpoint and received 401. Thus the first desktop attempt was NOT fully
offline; only generated source/test text and a fake key were involved, never
real credentials or private material. Testing was stopped and the fallback was
fixed before continuing. With the rebuilt backend, empty-file and failed-image
sends produced the localized local configuration error; the fresh application
log contained no external model HTTP requests. W17 records the guard and
candidate identities. All owned desktop/sidecar processes exited normally.

This closes the three notice-display cases for that specific native layout,
not the full six-language/narrow/light appearance matrix, history persistence,
real-model comprehension or direct-expert native acceptance.

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
# Full-regression format dispatch follow-up

The W17 frozen run exposed a stale picker-contract test. Replacing its literal
string reader with shared-registry wiring checks also found a real image dispatch
gap: TIFF/HEIC-family extensions were declared but not recognized by ingestion.
The image branch now uses the shared image extension list. Every declared format
is exercised through the actual dispatcher with parser seams, and undeclared
formats still fail closed. The focused format/vision/OCR selection passed 93 tests.
This proves dispatch consistency, not availability or quality of every decoder.
The legacy knowledge-image path's unconditional PNG MIME label still needs a
separate byte-format/normalization audit; it is not certified by these tests.
# Knowledge-image payload follow-up

After the frozen `59d5ba62` regression, the knowledge-image path was found to
label original JPEG/TIFF/etc. bytes as PNG. It now decodes actual bytes using
the already-required Pillow dependency, applies EXIF orientation, scales to a
1568-pixel long edge and sends real RGBA PNG with source metadata removed.
Limits are 30 MiB encoded input, 40 million source pixels and 12 MiB output.
Decode runs outside the event loop. These are allocation bounds, not a separate
process sandbox or a hard CPU deadline. No codec or dependency was installed.

Multi-frame inputs send only their first frame/page; both the model instruction
and persisted description disclose that limit. Undecodable HEIC/HEIF remains a
host-codec limitation, not a claim of support: local decode failure happens
before adapter construction, stores no description and does not masquerade as
a model refusal. Existing image-specific model refusal → local OCR ordering is
unchanged. Model-account/network errors retain their original meaning.

Real in-memory PNG/JPEG/TIFF/WEBP/GIF/BMP fixtures verify the adapter receives PNG
bytes, orientation and downscaling, metadata removal, first-frame disclosure,
corrupt-input rejection and all three limits before adapter creation. The focused
payload/vision/OCR/feed/rasterization/format suite passed 113 tests; Ruff and
whitespace checks passed. No live model was invoked. The earlier full frozen
run does not cover this subsequent source change; a new full release-source
regression remains required.

Implementation references: [Pillow image operations](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[orientation handling](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#orientation)
and [file lifecycle](https://pillow.readthedocs.io/en/stable/reference/open_files.html).

## Word source-locator follow-up

DOCX now uses the existing bounded OOXML reader rather than only
`Document.paragraphs`, which omitted table text. Body paragraphs, table-cell
paragraphs and nested textbox paragraphs are extracted in XML document order,
with `word/document.xml#paragraph=N` locators. Empty paragraphs count toward
positions; nested textbox text is not duplicated in its containing paragraph.
Tabs and line breaks survive. Field instructions are not executed; visible field
results are merely stored text, not recalculated values. External relationships
are never fetched. Existing archive/XML/input/output bounds apply to DOCX too.

Ephemeral extraction runs this reader off the request loop and bypasses optional
model compression for DOCX so its source locators are not rewritten. The knowledge
ingestion path shares extraction; its separately requested later compression and
chunking still do not promise preserved source locators. This is body XML text,
not rendered page numbering, layout/graphics understanding, headers, footers,
footnotes or comments. Richer PDF locators remain outstanding.

The focused Word/format/extract/API/ingest/OCR regression passed 46 tests, including
a real in-memory python-docx package with body and table text, malformed/entity/
alternate-encoding rejection, bounded truncation, nested textboxes and compression
bypass. Existing Starlette deprecation and aiosqlite teardown-guard diagnostics
remain. No user document, external URL or model was accessed by these tests.

## PDF page-source follow-up

PDF text-layer extraction now retains each original page separately before
formatting `[page N]` locators. Blank pages do not renumber later text. The OCR
threshold counts only stripped source text, never locator labels or blank-page
separators: even many blank pages around two characters still take the existing
OCR fallback. An all-blank result remains empty, and failed/empty OCR retains the
short source text with its original page locator. Optional tesseract output now
uses the same original-page convention. Native OCR and vision page paths already
carried page numbers and keep their existing routing/caps.

Ephemeral PDF extraction bypasses optional compression to preserve page locators.
Knowledge ingestion receives the located text; separately requested compression
and later chunking still do not guarantee preserved locators. These are physical
PDF page indexes, not printed page labels, table reconstruction or visual-layout
understanding. Mixed text/scan documents still use the existing whole-document
text threshold and are not certified for complete per-page visual understanding.
PDF parsing resource isolation/deadlines are unchanged by this work.

The final eight-file PDF/Word/format/ingest/extract/API regression passed 129 tests
in 6.02 seconds, including real pypdf-generated text/blank/text fixtures, OCR
page-order/empty-output cases, threshold discrimination, persisted-input wiring and
compression bypass. Targeted lint and whitespace checks passed; existing warning
and teardown diagnostics remain. No real user PDF or model was used.

## Structured attachment fidelity

Packaged-input inspection found that XLSX/PPTX and code/data attachments could
still enter the optional LLM cleanup path when callers supplied `compress=true`.
Five new regression cases first reproduced this call for XLSX, PPTX, TSX, JSON
and CSV. All structured-reader output now bypasses that cleanup, preserving
cell/slide locators, formula-vs-unverified-cache labels and code bytes. Direct
video metadata extraction gets the same protection; the video upload endpoint
already bypassed cleanup. Existing explicitly requested plain prose/URL cleanup
is retained. This does not certify later knowledge-library compression/chunking.

The four-file extraction/API/format/video selection passed 40 tests in 2.22s,
including the five no-model-call regressions. Changed-file lint and whitespace
checks passed. The frozen-sidecar smoke driver now also checks actual XLSX/PPTX
source locators, inert TSX text, fresh browser setup refusal and explicit video
capability limits. Packaged results are recorded separately in the release audit;
source-level tests alone do not establish those results.

## Composer async ownership and temporary URL policy (2026-09-19)

Four new tests reproduced stale attachment-list writes: concurrent file reads
could overwrite one another, a removed pending image could return, clearing a
batch could still append its results/start later files, and an unmounted composer
could notify its departed owner. Attachment commits now use the current list;
generation fences reject cleared/unmounted work. Pending-operation tokens keep
busy true until all active reads finish and reserve document/URL slots against
the nine-item cap. Old completion cannot clear a newer batch's busy state.
Unsent image previews are released on departure; already-sent preview ownership
is unchanged and `clear({revokeUrls:false})` retains their URLs for message chips.

The same inspection found that pasted URLs bypassed `allowUrlExtraction=false`
even though typed-URL detection honored it. A regression reproduced the backend
call from the disabled paste path. Both now honor the policy, and a policy
revision fences results from requests started before withdrawal, including an
off/on transition. This prevents stale result delivery; it does NOT claim to
abort an already-started HTTP request or undo earlier external reads. Explicit
file/image selection and the existing SSRF-hardened backend path are unchanged.

Ten new tests cover the four reproduced races, mixed URL/file completion, slot
reservation, clear/new-batch separation, sent-preview lifetime, disabled paste,
and in-flight policy withdrawal. The complete frontend run passed 243 files /
1,889 tests in 22.00s; TypeScript and production build (3.17s) passed. Existing
canvas/navigation and large-chunk warnings remain. Backend production source is
unchanged; no account, real model or user material was used. These changes have
not yet been included in a new native candidate or visually accepted.

## Malformed Office compression boundary (2026-09-19)

A real ZIP fixture with a reserved DEFLATE block type reproduced an uncaught
`zlib.error` in the shared OOXML reader. The reader now maps that decoder error
to `InputError("inputs.invalid")`; it does not expose decoder diagnostics or
treat malformed content as successful extraction. Existing unsupported ZIP
compression handling already returned this stable error and remains covered.

Six reader cases cover corrupt/unsupported compression across DOCX, XLSX and
PPTX. Three actual multipart API cases verify HTTP 400 and the exact localizable
error envelope, without mocking the extractor. The five-file format, extraction,
API and source-locator selection passed 55 tests in 6.35s; changed-file lint
passed. No model, account or user document was used. This is source-level
verification, not a new complete backend run or rebuilt native candidate.

## Extraction request-shape validation (2026-09-19)

Eight real HTTP regressions reproduced uncaught attribute errors for JSON
non-object bodies, non-string URLs, and a multipart text field named `file`.
The endpoint now verifies the parsed body's shape, URL type and Starlette
upload type before extraction. Invalid JSON syntax/encoding also maps to the
existing `inputs.invalid` envelope. Missing/empty URLs retain the previous
missing-input response; valid file and URL contracts are unchanged.

The malformed-shape cases forbid extractor invocation, establishing that these
requests cannot reach its network/model path. Ten new cases plus existing
format, extraction, API, DOCX and PDF source-locator tests passed: 65 tests in
3.20s. Changed-file lint and whitespace checks passed. These are offline source
checks, not full regression, UI or packaged acceptance.

Subsequent packaged verification: the W17 input-hardening candidate rebuild
includes these changes and the composer async/policy fixes. Its actual frozen
backend passed malformed-request and corrupt Office compression API checks,
alongside existing extraction/source-locator smoke. The full frontend suite
passed 1,889 tests. Refer to W17 for exact binary identities and limitations;
native visual acceptance and a fresh complete backend regression remain open.

The subsequent clean `3617083e` complete backend run passed 4,927 tests with
14 documented skips (492.62s), including all new input cases. W17 records its
JUnit identity and isolation. The full-regression gap is now closed for this
candidate; native visual and real selected-model acceptance remain open.
# Real mixed-PDF local OCR checkpoint — after `39705007`

Added `scripts/mixed_pdf_ocr_smoke.py`: a wholly synthetic in-memory PDF has
native text on pages 1 and 4, raster-only text on page 2, and blank page 3.
It verifies the scan has no text layer before extraction. Real macOS OCR
recovered the expected sentence and number, native text remained exact, page
locators were 1/2/4 and the partial flag was false. No model was configured or
called. The same fixture passed the actual authenticated multipart extract API
of a newly frozen executable, with compression requested to verify source
preservation. Its temporary process/profile were cleaned up.

The first fixture attempt failed honestly with `no_text`: visual inspection
showed a blank raster. The test PDF wrote a content stream directly instead of
an indirect object. Correcting fixture serialization, not product behavior,
made the page visibly readable and real OCR pass. Existing page-locator test
fixtures were corrected too. A new pixel-extrema assertion ensures the mixed
fixture really renders ink, preventing parseable-but-blank fixtures from
silently validating raster/OCR paths. Empty content-stream and recognizer
exception tests were also added. The revised combined selection passes
**78 tests in 4.19 seconds**, plus lint/whitespace checks.

Frozen output: `/tmp/arslan-candidate-build.BboGj4/dist-mixed-pdf`.
Backend SHA-256:
`50d6672fa9fb690a8e5e06c44711773ac2536d59c52127f5a6271b95596a0d24`.
The native app has NOT yet been refreshed. The original complete Python run
under `/tmp/arslan-mixed-pdf-regression.SVOpqO` remains live; these three new
test-only cases are separately verified, not retroactively included in that
run's future count. Full acceptance still needs current package/UI checks,
broader language/scan quality cases and the other W20 gates. The PDF skill's
visual-check requirement helped distinguish invalid test material from an
OCR product failure; no final PDF artifact was authored or delivered.

# Mixed text/drawing PDF source checkpoint — after `2879267c`

Inspection confirmed a document-wide text threshold caused mixed PDFs to return
only their text-layer pages, silently omitting drawing-only/scanned pages. The
parser now records pages with nonempty content streams but no extracted text;
truly empty pages remain blank. If the document has usable native text, only
those missing pages are rasterized and locally recognized, under the existing
page cap. Native text and original page numbers are preserved, recovered text
is explicitly marked local OCR, and no cloud model is called for this path.

Unavailable, failed, empty-result and over-budget pages receive explicit unread
page markers. A structured unresolved-page list accompanies the source text;
ephemeral extraction also returns its actual partial flag, so the existing
localized partial-attachment notice can be displayed. Knowledge ingestion keeps
the same source evidence. Blocking mixed-page OCR runs off the async event loop.
Rasterizer page, bitmap, image and document resources are closed.

The combined PDF/ingest/OCR/extract/API regression passed **75 tests in 8.11s**
with one existing Starlette/httpx deprecation. Six new tests use a real mixed
PDF and real rasterization with a stub recognizer to cover page selection,
unchanged native text, locator order, blank-page omission, unavailable/no-text
responses, page budget and knowledge ingestion without a model. Ruff and diff
checks pass. Full Python regression is running with isolated HOME at
`/tmp/arslan-mixed-pdf-regression.SVOpqO/full.xml` (not yet claimed passing).

This is not real-scanned-document OCR quality or packaged acceptance. The
current temporary app still predates this change. Next: collect the full run,
exercise an actual raster-text mixed fixture with the host recognizer, refresh
the package and verify partial/readback UI evidence. Pages containing BOTH a
usable text layer and additional scanned content remain a separate fidelity
case, not covered by the no-text-page detector. Full scan-only model/OCR policy
is unchanged. No genuine documents, accounts, costs or installation changes.
