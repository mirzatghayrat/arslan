# Memory relevance — local fallback and runtime evidence

The isolated `43649d7e` reproduction showed design preferences in an unrelated
arithmetic request. `personal_context.assemble` previously ranked by overlap but
then included every eligible entry until its budget filled, including zero-score
entries. Empty-query compatibility helpers had the same browse-all behavior.

## Current behavior

1. Existing owner/project/expert, confirmation, time and privacy filters run first.
   Tests spy on the scoring boundary to prove excluded projects never reach it.
2. A local lexical matcher normalizes Unicode, removes common function words,
   segments Chinese bigrams and expands a small set of common work nouns across
   English, Chinese, Japanese, Spanish, German and French. Confirmed structured
   style rules also carry a design retrieval term. This is relevance, not authority.
3. Zero-score entries do not enter the prompt. Empty queries use the transient
   current-task query when available; otherwise they do not fetch every entry.
   The receipt records `irrelevant` without copying the query or excluded text.
4. Explicit full-match inventory requests such as “Show my preferences” are an
   intentional list of relevant authorized entries, not an empty-query fallback.
   The same scope, privacy, time and token gates still apply. Quoted or appended
   prose does not match this inventory shortcut.
5. Related entries retain the existing count/token cap and stable ranking.
   Missing matches are not deletion: later related tasks can retrieve the memory.

Current-task text lives only in `TaskMemoryContext.query`. Compatibility prompt
helpers and empty recall queries use it; explicit retrieval queries take priority.
Workers use their own brief, not the parent's request. Headless and resumed tasks
may use their original instruction for retrieval without restoring explicit-save
authority. The actual user message passed to the model is not shortened by the
retrieval matcher's 8,000-character input bound.

## Evidence and limits

Pure tests cover all 36 report-query/preference locale pairs, negative arithmetic
and code queries, stopwords, word boundaries, common identity questions and explicit
inventory syntax. Runtime tests save through the real host tool loop, inspect a
later host adapter request and its persisted receipt, and then verify that a
related task can still use the stored preference. Restore, scope, sensitive/cloud,
versioning and task/worker boundary regressions remain separate positive controls.

No embedding model, remote reranker, network call or dependency download was added.
This matcher is a local lexical fallback, **not** a semantic model or a new SQLite
FTS integration. The existing FTS store is unchanged. Bounded aliases cannot
translate arbitrary concepts, recognize every paraphrase, or fully distinguish
all universal interaction rules from domain rules. Lexical overlap can still
produce false positives, and missing terms can produce false negatives. Those
limitations require broader scenario/real-model evaluation; they are not hidden
by calling this the complete personalization gate.

The final matcher/context/multi-turn/scoped-turn run passed **132 tests** in
63.54 seconds. Earlier expanded scope/restore/style/worker coverage passed 153
tests, and the resume/entry/tool/locality regression passed 53 tests; these sets
overlap and are not added together. Ruff and whitespace checks passed. The same
source still needs a complete frozen regression before release; focused results
alone do not update the older complete-run evidence in W17.
