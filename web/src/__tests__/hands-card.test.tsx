// 0.1.45 hands: the confirmation card for browser / Mac actions.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActionApprovalCard from "../components/ActionApprovalCard";
import { handsMessages } from "../locales/hands";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, string>) =>
  o ? `${k}:${Object.values(o).join("|")}` : k }) }));
afterEach(() => { cleanup(); useArslanStore.setState(initialArslanState(), true); });

/** `grant` is `scope` with one stretch cut out and nothing added: it begins with the scope's beginning and ends
 *  with the scope's end (the longest shared beginning is the best split; the rest of the grant must close the scope). */
function isScopeWithOneStretchCut(scope: string, grant: string): boolean {
  if (grant.length >= scope.length) return false;
  let shared = 0;
  while (shared < grant.length && grant[shared] === scope[shared]) shared++;
  return scope.endsWith(grant.slice(shared));
}

describe("action approval card", () => {
  it("shows an AppleScript in full and answers with the buttons", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ActionApprovalCard kind="mac_script" target="AppleScript" detail={'tell application "Reminders" to count reminders'}
      onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByTestId("action-script")).toHaveTextContent('tell application "Reminders" to count reminders');
    fireEvent.click(screen.getByTestId("action-allow"));
    fireEvent.click(screen.getByTestId("action-deny"));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("names the website for a browser action", () => {
    render(<ActionApprovalCard kind="browser_site" target="https://github.com" detail="click" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("hands.title.browser_site:https://github.com")).toBeInTheDocument();
  });

  it("the store holds a job's action card and raises the spoken notice", () => {
    useArslanStore.getState().handleFrame({ type: "propose_action", call_id: "a1", kind: "mac_shortcut",
      target: "Log water", detail: "Run the Shortcut", background: true });
    expect(useArslanStore.getState().pendingActions).toMatchObject([{ callId: "a1", kind: "mac_shortcut" }]);
    expect(useArslanStore.getState().jobNotice).toMatchObject({ kind: "needs_approval" });
  });

  it("every grant line is its scope line with one stretch cut out and nothing added, in all six languages", () => {
    // 0.1.61: a card that offers a choice drops how long (the scope sentence) and keeps what is granted (the grant).
    // Only a kind that has a scope line has a grant. The cut is one stretch of the scope: the grant begins with the
    // scope's beginning and ends with the scope's end, and the words between them are the ones left out.
    for (const [lang, messages] of Object.entries(handsMessages)) {
      for (const [kind, grant] of Object.entries(messages.grant)) {
        const scope = (messages.scope as Record<string, string>)[kind];
        expect(scope, `${lang}.scope.${kind}`).toBeTruthy();
        expect(grant.trim(), `${lang}.grant.${kind}`).not.toBe("");
        expect(isScopeWithOneStretchCut(scope, grant), `${lang}.grant.${kind} is ${scope} minus one stretch`).toBe(true);
      }
    }
  });

  it("the guard itself: a grant that adds a word, rewords, or cuts two stretches is not a cut of its scope", () => {
    const scope = "Allows clicking and typing on this website for this piece of work only. Arslan never types passwords.";
    expect(isScopeWithOneStretchCut(scope, "Allows clicking and typing on this website. Arslan never types passwords.")).toBe(true);
    expect(isScopeWithOneStretchCut(scope, "Allows clicking and typing on this website for this piece of work only.")).toBe(true);   // the end cut
    expect(isScopeWithOneStretchCut(scope, "Arslan never types passwords.")).toBe(true);                                             // the beginning cut
    expect(isScopeWithOneStretchCut(scope, scope)).toBe(false);                                                                      // nothing cut
    expect(isScopeWithOneStretchCut(scope, "Allows clicking and typing on this site. Arslan never types passwords.")).toBe(false);  // reworded
    expect(isScopeWithOneStretchCut(scope, "Allows clicking and typing on this website, always. Arslan never types passwords.")).toBe(false);   // added
    expect(isScopeWithOneStretchCut(scope, "Allows typing on this website for this piece of work only. Arslan never types passwords.")).toBe(true);   // a cut from the middle
    expect(isScopeWithOneStretchCut(scope, "Allows typing on this website. Arslan never types passwords.")).toBe(false);             // that cut and another: two
    expect(isScopeWithOneStretchCut(scope, "Allows clicking and typing on this website. Arslan never")).toBe(false);                 // a tail that is only somewhere in the scope
    expect(isScopeWithOneStretchCut(scope, "Allows clicking on this website for this piece of work only. Arslan types passwords.")).toBe(false);   // two cuts
    expect(isScopeWithOneStretchCut(scope, "")).toBe(true);                                                                          // everything cut (the caller rejects an empty grant)
  });

  it("a look attaches a window screenshot by default, so neither desktop_app line (it covers looking too) says there is none, in any language", () => {
    // server/services/hands_service.py (settings: screenshots on unless turned off) and hands_tools.py (a look attaches it).
    const denial: Record<string, RegExp> = {
      en: /no screenshot/i, zh: /不截图/, ja: /スクリーンショットは撮りません/,
      es: /sin capturas/i, de: /ohne Bildschirmfoto/i, fr: /sans capture d[’']écran/i,
    };
    expect(Object.keys(denial).sort()).toEqual(Object.keys(handsMessages).sort());
    for (const [lang, messages] of Object.entries(handsMessages)) {
      expect(messages.scope.desktop_app, `${lang}.scope.desktop_app`).not.toMatch(denial[lang]);
      expect(messages.grant.desktop_app, `${lang}.grant.desktop_app`).not.toMatch(denial[lang]);
      expect(messages.title.desktop_app, `${lang}.title.desktop_app`).not.toMatch(denial[lang]);
    }
  });

  it("has the same keys in all six languages", () => {
    const flat = (o: object, p = ""): string[] => Object.entries(o).flatMap(([k, v]) =>
      typeof v === "object" ? flat(v, `${p}${k}.`) : [`${p}${k}`]);
    const keys = flat(handsMessages.en).sort();
    for (const messages of Object.values(handsMessages)) expect(flat(messages).sort()).toEqual(keys);
  });
});
