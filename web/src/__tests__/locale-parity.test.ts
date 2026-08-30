/**
 * Locale parity test — all 6 locale JSONs must have the exact same nested key set.
 * Fails immediately if any locale drifts from en (the reference).
 */

import { describe, it, expect } from "vitest";

import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

type JsonObj = Record<string, unknown>;

/** Recursively collect all dot-separated key paths from a JSON object. */
function collectKeys(obj: JsonObj, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      keys.push(...collectKeys(v as JsonObj, path));
    } else {
      keys.push(path);
    }
  }
  return keys.sort();
}

const LOCALES: Record<string, JsonObj> = { en, zh, ja, es, de, fr };
const enKeys = collectKeys(en as JsonObj);

describe("locale parity", () => {
  it("en locale has 1335 keys (baseline guard)", () => {
    // 1318 → 1335: the first-run wizard redesign — the four-beat "how it
    // works" tour (title + typed line + 4×title/body), the catalog capability
    // caption, the test-before-save states (test & save / testing / ok /
    // generic failure / save anyway), and the hello step's name prompt,
    // placeholder, hint and enter button. getStarted, stepOf and finish left
    // with the steps that used them (welcome step dropped, dots replaced the
    // step counter, "enter" replaced "finish").
    // 1314 → 1318: the OpenRouter sign-in on the first-run wizard — button,
    // waiting line, the stated paid-fallback (a silent one would 402 on the
    // exact zero-card user the button exists for), and the "or" divider.
    // 1313 → 1314: updater.checking — the line beside the dot-matrix sweep while
    // a menu-triggered update check is in flight. One key: the state is transient
    // and offers no actions, so it has no button copy.
    // 1293 → 1313: the model-roles section — nav label, lede, five slot labels,
    // five purpose lines, five fallback sentences, the unset option, the
    // add-a-model link and the embedding pointer. Five purposes rather than one
    // shared sentence because five unexplained dropdowns are five controls
    // nobody dares touch, and five fallback sentences because an empty slot
    // means three different things depending on which slot it is.
    // 1240 → 1246: the self-hosted SearXNG address field — its label, the test
    // button, and one sentence per verdict. Four sentences rather than one
    // because the four failures have four different fixes, and the most common
    // of them (json missing from search.formats) is the one most easily misread
    // as a mistyped address.
    // 780 → 781: S3-M1 added chat.stopRun (the run-cancelled marker reuses the
    // existing working.stalled key instead of adding a duplicate).
    // 781 → 793: S3-M3 added the usage.* section (Diagnostics usage card —
    // title/daily/empty/notCovered + 3 range + 5 column keys).
    // 793 → 839: S3-M4 added the scheduled.* section (Diagnostics scheduled
    // tasks — card + badges + actions + history + create/edit form, 46 keys).
    // 839 → 854: Provider-P2 added settings model-combobox keys (refresh,
    // custom-id row, stale/last-updated hints, ollama empty state, base URL
    // label, relative-time units, capability chips — 15 keys).
    // 854 → 858: Provider-P3 added custom-provider keys (required base_url
    // hint, quick-fill label, Ollama-remote chip, compatibility note — 4 keys).
    // 858 → 862: Provider-P4 added connectivity-dot tooltips (healthDotModels/
    // NoList/Unreachable/Unknown — 4 keys).
    // 862 → 872: Settings-T1 added the SettingsShell side-nav keys (settings.
    // navProviders/navSearch/navAppearance/navAccess/navMemory/navAdvanced/
    // navScheduled/navUsage + navComingSoon + placeholderHint — 10 keys).
    // 872 → 873: Settings-T2 added settings.navRegion (side-nav aria-label).
    // 873 → 878: Settings-T3 added the ConnectionTester + CapabilityBadges keys
    // (capabilitiesLabel, testConnection, deepTest, deepTestOk,
    // reachableNoListNote — 5 keys).
    // 878 → 885: Settings-T5 i18n'd the retention label/hint, the spawn-mode
    // desc + 3 option labels, the page-header lore, and the footer note
    // (spawnModeDesc/Auto/Interactive/Strict, retentionLabel/Hint, headerLore,
    // footerNote = +8) and removed the now-orphaned settings.sectionInterface
    // (−1) → net +7.
    // 885 → 886: Settings-T6 replaced the top Save button with instant auto-save
    // — removed the now-dead btnSave/btnSaving (−2) and added the auto-save
    // status keys savingLabel/savedTick/saveFailed (+3) → net +1.
    // 886 → 904: E9-b Task 4d added the evolution.diag.* block for the inbox
    // eligibility panel (title + pick_spawn + verdict_* codes + chain_* +
    // auto_off = 18 keys). Review fix: swapped the unreachable
    // verdict_drought_holdout_split for chain_holdout_plain (−1 +1, net 0).
    // 904 → 908: provider-key-input fix added the saved-config key-field keys
    // (settings.keyEnter/keySavedReplace/keyReenter/keyUndecryptableReason —
    // fresh-entry placeholder states + the honest undecryptable reason, 4 keys).
    // 908 → 913: Task 10 (S4.1-C) added the inbound-MCP-server toggle +
    // generate-token control keys (settings.labelMcpServer/mcpServerDesc +
    // settings.mcpToken.generate/generating/generateError — 5 keys).
    // 913 → 914: BUG2 (invite-accept honest notice) added
    // 954 → 1203: (b) dispatch cap — settings label/desc/unset, evolution.card.estimate_tokens,
    //             settings.evolutionAutoSpendWarningCapped
    // 951 → 954: S4.2-a settings.labelEvolutionAuto / evolutionAutoDesc / evolutionAutoSpendWarning
    // 942 → 951: F1 brain.temporal.* (as-of slider + lineage), 9 keys x 6 languages
    // chat.roster_joined_no_pending — the never-silent explanation when a card
    // accept finds no parked task (joined only; @ to hand off).
    // 1203 → 1202: batch two removed sidebar.node_version. The build tag it
    //              rendered had read "0630" since June while the app shipped
    //              0.1.11, so the one thing it existed to prevent — mistaking a
    //              stale UI for a current one — is what it was causing.
    // 1202 → 1206: the OCR language picker (label, follows-UI hint, cap hint,
    //              and the honest "this system has no recognition" line).
    // 1206 → 1213: brain search (no-hits, count, two ranking labels,
    //              truncated notice, and the two mode hints).
    // 1213 → 1221: brain branch kinds + provenance labels, moved out of the
    //              backend where they were Chinese literals no frontend guard
    //              could see.
    // 1221 → 1240: gate item ① — the anomaly/recap/scheduled sentences moved
    //              out of the backend, where they were Chinese f-strings that
    //              no interface could translate.
    // 1240 → 1246: gate item ② (empty states). +13 new (a body and, where the
    //              next step is not already on screen, an action for each Tier A
    //              panel; plus the filtered-vs-empty split), 5 existing strings
    //              rewritten in place, and −7 DEAD keys deleted: dashboard.
    //              empty_title/empty_body, conversation.empty, facts.empty,
    //              equipment.empty, spawn_edit.empty, brain.noConnections had
    //              zero call sites in web/src. One of them, "Create your first
    //              AI spawn to get started.", was friendlier than the copy that
    //              actually shipped — dead copy that reads better than live copy
    //              is a trap for whoever greps next.
    // 1246 → 1257: gate item ③ (Settings redesign). +16 new — the three group
    //              headings, the Models/Automation nav labels, the automation
    //              lede and the curation toggle's copy (including the note that
    //              this one has NO cap of its own), the search box, and the two
    //              chrome strings that were hardcoded English: the page H1 (which
    //              also called this page "Diagnostics") and the offline banner's
    //              body. −5 killed with the placeholder tabs they belonged to:
    //              navProviders, navScheduled, navUsage, navComingSoon,
    //              placeholderHint — all verified to have zero call sites first.
    // 1257 → 1261: the overlay-dismissal round added common.discard_* — Escape in
    //              a DIRTY editor asks before closing (ruling ①A) instead of
    //              destroying work on a reflexive keystroke.
    // 1261 → 1264: the header/rail polish batch added orchestrator.shell_on /
    //              shell_off / browser_soon — tooltips for the two new status
    //              indicators, which carry meaning no icon can.
    // 1264 → 1265: settings.modeSystem — "follow the OS" is a third CHOICE, and a
    // 1268 → 1269: capabilityTableNote — the routing table's five columns are
    // 0-10 model ratings, and "Tool aptitude" reads as the same thing as the
    // transport notice next to it. The caption says which is which.
    // 1265 → 1268: tool-transport notice in Settings — title +
    // unsupported + unverified, warning that a provider drops tool
    // definitions so equipped tools and MCP never fire. (Named
    // Anthropic/Gemini when written; G1 fixed Anthropic, and the strings
    // themselves never named a provider — which is why the copy did not
    // have to change with it.)
    //              two-state toggle had no way to say it.
    // 1269 → 1277: the crypto diagnosis — title, five verdict paragraphs, and two
    //              count labels. It replaces one hard-coded sentence that named
    //              ARSLAN_SECRET_KEY as the cause of what was a SALT change; the
    //              backend now computes a verdict and each one gets its own words,
    //              because two verdicts sharing a paragraph is a diagnosis that
    //              cannot distinguish the thing it exists to distinguish.
    // 1277 → 1282: search failures that name WHICH failure (rate limit, quota,
    //              rejected key — three different remedies) plus provenance, with
    //              and without the best-effort marker. search_fail already existed
    //              and was reworded: it used to promise "retrying differently" on
    //              every failure, which the code never did.
    // 1282 → 1286: the search-key label, its placeholder and the GitHub-token
    //              label finally come from locale files. All three were hardcoded
    //              English, and search_api_key_hint (already in six languages)
    //              was rendered by nobody — so "there is a free key" was never
    //              seen, and now "you do not need one" would not have been either.
    // 1286 → 1287: brain.stale_note — mark_stale now takes a fact out of injection
    //              and recall, so the entry panel has to say so; a fact that silently
    //              stops being used while the graph still shows it in full reads as
    //              the model forgetting rather than as a mark someone set.
    // 1335 → 1342: capabilities.dossier.manifest.* — the arslan.plugin.json
    //              card (author-shipped config, secret-slot inputs, skill import,
    //              the expose SUGGESTION rendered as advice not action, and the
    //              honest invalid-manifest line that never hides the guess path).
    // 1342 → 1349: Discover UX round — hero.researching (busy label),
    //              hero.kind.{all,mcp,skill,agent,other} (search filter chips /
    //              row type badges), dossier.overview_label (the plain-language
    //              "what this is" card that replaced the useless value line).
    // 1349 → 1359: the workspace file tools (P1). wswrite.* is the write-grant
    //              card — it names the DIRECTORY being granted, not the file,
    //              because that is what the user is actually agreeing to, and
    //              says the grant lasts the session. settings.workspaceDir* is
    //              the picker plus the hint that an empty value means the file
    //              tools are not offered at all.
    // 1359 → 1363: settings.heartbeat* — the periodic checklist (P2 §1.3). The
    //              description says what a background run CANNOT do, because
    //              the whole safety argument is that it only looks and reports;
    //              the spend note says each check costs tokens, and that an
    //              empty list runs nothing.
    // 1363 → 1368: schedgrant.* — the scheduling grant card (P2 §1.2). Its
    //              scope line says what a scheduled run CANNOT do, because the
    //              user is approving unattended runs and that limit is what
    //              makes the approval safe to give.
    // 1368 → 1370: settings.lanDiscovery* — seeing the local network (P3a).
    //              The description leads with what it does NOT do (connect, log
    //              in, run anything), because a network scan is the kind of
    //              capability a person should be able to judge from the label.
    // 1370 → 1385: settings.ssh* + settings.sshKey* + runcmd.remote* (P3b).
    //              Reaching another machine needed more copy than any switch so
    //              far, and deliberately so: the toggle names what a scheduled
    //              task can NEVER do with it, the key panel says removal here
    //              cannot delete the line pasted on the far machine, and the
    //              confirm card gets its own label/warning/fingerprint strings
    //              because "this runs somewhere else" must not arrive as a
    //              footnote on a card that otherwise looks local.
    // 1385 → 1396: settings.sshNode* + enroll.* (P3c). Two ideas needed saying
    //               in words rather than being left to inference, and each costs
    //               a string: enrolling a machine does NOT stop commands asking
    //               (the ruling), and forgetting one here cannot delete the key
    //               line pasted on that machine (only its owner can).
    // 1396 → 1402: nav.* for the six page headers that were rendering their own
    //               i18n key on screen. `t(`nav.${activeSection}`)` needed a key
    //               per SECTION and `nav` had four unrelated ones; only
    //               `settings` happened to match. Found by looking at the running
    //               app, not by any of the 1514 tests that were green while it
    //               was on screen — see nav-titles.test.ts.
    // 1402 → 1407: capabilities.filter.* — searching what you ALREADY have.
    //               The Discover box searches GitHub for things you do not have;
    //               nothing looked inward. The count string is not decoration:
    //               without it a query that hides everything is indistinguishable
    //               from an empty library.
    // 1407 → 1409: brain.inbox.keyhint + aria_list — keyboard triage over the
    //               memory proposals (F2). The hint is shown rather than left to
    //               be discovered: an unadvertised shortcut is one nobody uses.
    // 1409 → 1412: settings.labelDefaultRead + settings.defaultReadDesc +
    //               firstRun.readNotice — the default-read toggle and its
    //               first-run consent line (spec 2026-08-24).
    expect(enKeys).toHaveLength(1412);
  });

  for (const [lang, data] of Object.entries(LOCALES)) {
    if (lang === "en") continue;

    it(`${lang} has the same keys as en`, () => {
      const langKeys = collectKeys(data as JsonObj);
      expect(langKeys).toEqual(enKeys);
    });
  }
});
