# ADR-001 — retain the native Python execution core

Decision date: 2026-09-14. Status: accepted for this implementation. Revisit only with measured net benefit, not as an open-ended framework search.

## Compared surface

Pi source pinned to `ceea48f5d5d12fd7915dfefba2835ccd55f23bb9`, package `@earendil-works/pi-agent-core` 0.85.1, MIT, Node >=22.19.0. Inspected its [agent interface documentation](https://github.com/earendil-works/pi/blob/ceea48f5d5d12fd7915dfefba2835ccd55f23bb9/packages/agent/README.md), [manifest](https://github.com/earendil-works/pi/blob/ceea48f5d5d12fd7915dfefba2835ccd55f23bb9/packages/agent/package.json), and [license](https://github.com/earendil-works/pi/blob/ceea48f5d5d12fd7915dfefba2835ccd55f23bb9/LICENSE).

| Boundary | Pi documented interface | Arslan decision/evidence |
| --- | --- | --- |
| Events | Agent/turn/message/tool events; subscriptions may be awaited | Keep existing stream/tool events and RunRecorder; add versioned task events in W07 |
| Pre-tool authorization | beforeToolCall can block; afterToolCall is too late to prevent an effect | Keep per-call tool resolution and approval callbacks before executor invocation |
| Tool ordering | Parallel default, sequential mode available | Preserve serial side-effect dispatch; explicit independent workers later |
| Cancellation | Active run signal; stopping after a turn is not cancellation of current work | Preserve asyncio cancellation through actual host, dispatcher, and recipe entry points |
| Provider state | Conversion hooks separate application and model messages | Preserve existing provider-native opaque continuation fields; Gemini round-trip regression remains required |
| Persistence/packaging | Separate SQLite backend, Node runtime and additional packages | Avoid a Node↔Python control boundary plus duplicate session lifecycle in the existing Python sidecar |

Native conformance now exercises actual host answer, expert dispatcher, and recipe execution against synthetic model/tool adapters, with real isolated Run/RunStep persistence. Eleven new tests cover allowed/denied tools, caller identity, outer cancellation, and confirmation callbacks. Existing native/provider/recipe suites cover their wider behavior.

The conformance pass exposed two native defects: workspace/schedule confirmation callbacks were omitted in normal native tool dispatch; fetch-budget refusal lacked the usual trace/history record. Both were corrected with regression coverage. This is concrete repair evidence, not proof that every native safety boundary is complete.

## Why retain native

Pi offers useful composable interfaces, but the inspected surface does not establish enough benefit to justify a second process/runtime protocol, provider translation, approval bridge and persistence integration. The approved replacement threshold is unmet. Stop the comparison here and improve the existing single execution path.

No Pi package was installed or benchmarked. No real model/provider quality claim is made. No source code was copied. This is a bounded source/interface comparison plus native synthetic conformance, **not** a head-to-head performance benchmark.
