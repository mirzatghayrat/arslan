# Staged delivery amendment — 2026-09-19

The user requested a releasable intermediate version and staged tasks because
the all-at-once goal has consumed too much usage. This supersedes the previous
requirement that every v1.2 work package finish before any intermediate release.
It does not assert that the full companion goal is complete or relax safety.

## Stage 1: bounded preview candidate

Freeze feature development at `84433af1`. Prepare an explicitly limited preview
candidate of implemented capabilities, not a fully accepted v1.2 stable release.
Do not start concurrent follow-on tasks automatically.

Required work only:

1. Verify unsupported credential/account and sensitive browser actions remain
   disabled, and release-facing copy does not promise unavailable capabilities.
2. Refresh the temporary package for the last reader-stop fix; perform focused
   package/startup/data-retention/reader-stop checks. Reuse existing scoped test
   evidence; rerun broad suites only when new changes invalidate that evidence.
3. Record the actual release channel, version, packaging/signing requirements,
   known limitations and rollback instructions. Prepare artifacts through the
   established release workflow. Do not label an unsigned temporary app as an
   officially distributable signed release.
4. Present candidate and remaining human publication steps. Do not replace the
   installed app or publish automatically; the user retains the Publish action.

Known limitations must include read-only public browser interaction, disabled
credential-backed account workflows, sampled video frames/no transcript backend,
and incomplete full locale/real-model/independent security acceptance. Do not
claim real-model quality based on synthetic tests.

Release blockers remain data loss, authorization bypass, unsafe secret handling,
startup failure and broken advertised core paths. Deferred feature completeness
alone is not a blocker for an accurately labelled limited preview. If an unsafe
path is reachable, fix it or explicitly disable that path before distribution.

## Subsequent bounded tasks (backlog, not automatically dispatched)

- Browser interaction and authorization: W11/W12/W13/W19; establish reviewed
  boundaries before genuine credentials or account actions.
- Media and task outcomes: W15/W20 plus real-model evaluations; obtain explicit
  authorization for required accounts, inputs, downloads or costs.
- Compatibility and stable-release acceptance: complete W17/W21 native recovery,
  locale/layout/old-data matrix and final human acceptance.

Each task starts with a finite deliverable and acceptance list, reports its
remaining gaps, and ends at its milestone. The complete v1.2 goal remains open
until those requirements are actually achieved; preview delivery is not its
completion claim.
