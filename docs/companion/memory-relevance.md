# Memory relevance — local FTS and multilingual supplement

The isolated `43649d7e` reproduction showed design preferences in an unrelated
arithmetic request. `personal_context.assemble` previously ranked by overlap but
then included every eligible entry until its budget filled, including zero-score
entries. Empty-query compatibility helpers had the same browse-all behavior.

## Current behavior

1. Existing owner/project/expert, confirmation, time and privacy filters run first.
   Tests spy on the scoring boundary to prove excluded projects never reach it.
2. Eligible current revisions are matched against the existing local FTS5 index.
   Only allowed entry IDs are queried, in bounded batches; indexed content must
   equal the approved current revision. The query uses bounded, quoted literal
   terms, never raw FTS operators from task text. No global-corpus rank or indexed
   body is returned to the context builder. FTS matches supply a positive local
   relevance signal, not permission or model-adoption evidence.
3. A complementary local lexical matcher normalizes Unicode, removes common function words,
   segments Chinese bigrams and expands a small set of common work nouns across
   English, Chinese, Japanese, Spanish, German and French. Confirmed structured
   style rules also carry a design retrieval term. This is relevance, not authority.
4. Entries matching neither FTS nor the supplement do not enter the prompt. Empty queries use the transient
   current-task query when available; otherwise they do not fetch every entry.
   The receipt records `irrelevant` without copying the query or excluded text.
5. Explicit full-match inventory requests such as “Show my preferences” are an
   intentional list of relevant authorized entries, not an empty-query fallback.
   The same scope, privacy, time and token gates still apply. Quoted or appended
   prose does not match this inventory shortcut.
6. Related entries retain the existing count/token cap and stable ranking.
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
The existing FTS store is now consulted; its schema and repository-controlled
update/delete lifecycle are unchanged. A schema-only prepared database without
that index retains lexical matching, and stale index text cannot independently
select a newer revision. The supplement remains necessary for unsegmented CJK
and common cross-language concepts that the original-text index does not match.
This is **not** a semantic model. Bounded aliases cannot
translate arbitrary concepts, recognize every paraphrase, or fully distinguish
all universal interaction rules from domain rules. Lexical overlap can still
produce false positives, and missing terms can produce false negatives. Those
limitations require broader scenario/real-model evaluation; they are not hidden
by calling this the complete personalization gate.

Index integration tests activate the real SQLite store and prove FTS selection
independently of the lexical supplement. They cover pre-query owner/project/
sensitivity filtering, revision changes, deliberately stale index data, deletion,
missing-index fallback, all six query languages, literal operator-like input,
205 eligible IDs across batches, and the existing final token/count budget.
These fixtures contain no real personal data. The context builder still fetches
eligible current rows for the multilingual supplement; this is not a claim of
large-store retrieval performance or embedding-quality relevance.

The combined FTS/context/activation/repository/restore/multi-turn/tool/locality/API
regression passed **200 tests in 68.09 seconds**, with one existing TestClient
deprecation warning. Ruff and whitespace checks passed. Initial fixture setup
omitted the required scope field and was corrected. A first expanded invocation
interleaved root/server paths and stopped with a missing `execution_db` fixture
after 112 passes; rerunning with server files grouped completed successfully.
No production fixture or permission behavior was weakened to obtain that result.
The complete 4,704-test backend result in W17 predates FTS integration, so a new
full frozen run remains required for this source. Frontend source is unchanged.

The final matcher/context/multi-turn/scoped-turn run passed **132 tests** in
63.54 seconds. Earlier expanded scope/restore/style/worker coverage passed 153
tests, and the resume/entry/tool/locality regression passed 53 tests; these sets
overlap and are not added together. Ruff and whitespace checks passed. A complete
frozen backend run on clean `bec04286` then passed **4,701 tests, with 14 skips
and 19 warnings in 440.60 seconds**. The isolated report is
`/tmp/arslan-memory-relevance-regression.sfva4B/backend.xml`; skips, warnings and
remaining product gates are recorded in W17. This is engineering evidence, not
real-model acceptance or release approval.
