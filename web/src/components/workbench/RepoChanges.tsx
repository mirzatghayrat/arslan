import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, GitBranch } from "lucide-react";
import type { RepoChanges as Repo, RepoPr } from "../../api/files";
import { baseName } from "../../lib/fileKinds";
import { useWorkbench } from "../../stores/workbenchStore";
import { isolate } from "../CapabilitySwitches";
import { opensDiff } from "./DiffReader";

const KIND_COLOR = { made: "text-success", edited: "text-muted-foreground", deleted: "text-danger" } as const;
const STATE_STYLE: Record<RepoPr["state"] | "draft", string> = {
  open: "text-success bg-success/10", draft: "text-muted-foreground bg-fill", merged: "text-info bg-info/10",
  closed: "text-danger bg-danger/10",
};
const CHECK_STYLE = { passed: "text-success", failing: "text-danger", running: "text-muted-foreground" } as const;
const link = "shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-foreground/5 hover:text-foreground";
const SLUG = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

/** git's own errors (#587): only these two hide the repo; anything else (gh's `prs_error`, an unknown key) does not. */
export const gitError = (repo: Repo) => repo.error === "no_git" || repo.error === "unreadable";

/** A PR's page, built from the repo's github.com slug and the PR's number, never a link from outside (#588 review). */
export function prLink(slug: string | null, number: number): string | null {
  return slug && SLUG.test(slug) && Number.isSafeInteger(number) && number > 0
    ? `https://github.com/${slug}/pull/${number}` : null;
}

/**
 * DIFF2-2 (v0.1.64; the user's picks on the DIFF2-0 mock, 2026-10-31): Overview's Changes for a folder in a git repo,
 * as Claude desktop shows it: the branch against its base, its PRs with their checks (a PR opens in the Browser tab),
 * the commits (folded) and every file changed since the branch left its base, committed or not. A text file opens
 * its diff in DiffReader. Read only. Branch names, subjects, titles and paths come from the repo or GitHub: shown as
 * plain text through isolate().
 */
export default function RepoChanges({ repo, conversationId, folder }: {
  repo: Repo; conversationId: string; folder: string;
}) {
  const { t } = useTranslation();
  const openReader = useWorkbench((s) => s.openReader);
  const openUrl = useWorkbench((s) => s.openUrl);
  const [showCommits, setShowCommits] = useState(false);
  const head = <div className="mt-1.5 flex min-w-0 items-baseline gap-1.5">
    <b className="shrink-0 text-[12.5px] font-semibold">{isolate(baseName(folder))}</b>
    <span className="min-w-0 truncate text-[11px] text-subtle-foreground" title={isolate(folder)}>{isolate(folder)}</span>
  </div>;
  if (gitError(repo)) {
    return <div data-testid="overview-repo-error">{head}
      <p className="mt-1 text-[12px] text-muted-foreground" data-testid="repo-error">
        {t(repo.error === "no_git" ? "workbench.repoNoGit" : "workbench.repoUnreadable")}</p></div>;
  }
  const added = repo.files.reduce((n, f) => n + (f.added ?? 0), 0);
  const removed = repo.files.reduce((n, f) => n + (f.removed ?? 0), 0);
  const chip = "inline-flex max-w-full min-w-0 items-center gap-1 rounded-md bg-fill px-1.5 font-mono text-[11.5px]";
  return (
    <div data-testid="overview-repo">
      {head}
      <p className="mt-0.5 text-[11px] text-subtle-foreground">{t("workbench.repoReadOnly")}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        <span className={chip} data-testid="repo-branch"><GitBranch size={12} aria-hidden className="shrink-0" />
          <span className="truncate">{repo.branch ? isolate(repo.branch) : t("workbench.repoDetached", { sha: repo.detached })}</span></span>
        {repo.base && <><span className="text-subtle-foreground" aria-hidden>→</span>
          <span className={chip}><span className="truncate">{isolate(repo.base)}</span></span></>}
        <span className="text-[11.5px] text-muted-foreground">{repo.files.length === 0
          ? t("workbench.repoNothing")
          : t("workbench.repoAhead", { count: repo.commits.length })}</span>
        {repo.files.length > 0 && <span className="font-mono text-[11px]" data-testid="repo-totals">
          <span className="text-success">+{added}</span> <span className="text-danger">−{removed}</span></span>}
      </div>

      {/* PRs belong to a branch: none on a detached HEAD, none for a repo not on github.com. */}
      {repo.github && repo.branch && <div className="mt-2">
        <div className="text-[11px] font-medium text-muted-foreground">{t("workbench.repoPrs")}</div>
        {repo.signed_in === false
          // gh's own sign-in (#588 review, F5): Settings can't do it, so say what does.
          ? <p className="mt-1 rounded-md border border-dashed border-border-strong px-2 py-1.5 text-[11.5px] text-muted-foreground"
            data-testid="repo-signin">{t("workbench.repoSignIn")}</p>
          : repo.prs.length === 0
            ? <p className="mt-1 text-[11.5px] text-muted-foreground">{t(repo.prs_error ? "workbench.repoPrsUnavailable" : "workbench.repoNoPr")}</p>
            : <ul className="mt-0.5 space-y-0.5">{repo.prs.map((pr) => {
              const known = pr.state === "open" || pr.state === "closed" || pr.state === "merged";
              const state = pr.draft && pr.state === "open" ? "draft" : pr.state;
              const url = prLink(repo.github, pr.number);
              const parts = <>
                <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground">#{pr.number}</span>
                <span className="min-w-0 flex-1 truncate text-[12.5px]">{isolate(pr.title)}</span>
                {known && <span className={`shrink-0 rounded-full px-1.5 text-[10.5px] font-semibold ${STATE_STYLE[state]}`}>
                  {t(`workbench.pr_${state}`)}</span>}
                {pr.checks && pr.checks in CHECK_STYLE && <span className={`shrink-0 text-[11px] ${CHECK_STYLE[pr.checks]}`}
                  data-testid="repo-pr-checks">{t(`workbench.checks_${pr.checks}`)}</span>}
              </>;
              const row = "flex w-full min-w-0 items-center gap-2 py-0.5";
              return <li key={pr.number} data-testid="repo-pr">{url
                ? <button type="button" className={`${row} -mx-1 rounded-md px-1 text-left hover:bg-foreground/[0.04]`}
                  onClick={() => openUrl(url)} data-testid="repo-pr-open">{parts}
                  <span className="shrink-0 text-[11px] text-subtle-foreground" aria-hidden>↗</span></button>
                : <div className={row}>{parts}</div>}</li>;
            })}</ul>}
      </div>}

      {repo.commits.length > 0 && <div className="mt-2">
        <button type="button" className={`${link} -ml-1.5`} aria-expanded={showCommits} onClick={() => setShowCommits(!showCommits)}
          data-testid="repo-commits-toggle">{showCommits ? "▾" : "▸"} {t("workbench.repoCommits", { count: repo.commits.length })}</button>
        {showCommits && <ul className="mt-0.5 space-y-0.5" data-testid="repo-commits">{repo.commits.map((c) => (
          <li key={c.sha} className="flex min-w-0 gap-2 text-[12px]">
            <code className="shrink-0 font-mono text-[11px] text-subtle-foreground">{c.sha}</code>
            <span className="min-w-0 truncate">{isolate(c.subject)}</span></li>))}</ul>}
      </div>}

      {repo.files.length > 0 && <ul className="mt-2 space-y-0.5" data-testid="repo-files">{repo.files.map((f) => {
        const i = f.path.lastIndexOf("/");
        const [name, dir] = i < 0 ? [f.path, ""] : [f.path.slice(i + 1), f.path.slice(0, i + 1)];
        const parts = <>
          <span className={`min-w-12 shrink-0 text-[11px] ${KIND_COLOR[f.kind]}`}>{t(`workbench.${f.kind}`)}</span>
          <span className="min-w-0 max-w-[60%] truncate">{isolate(name)}</span>
          {dir && <span className="min-w-0 flex-1 truncate text-[11px] text-subtle-foreground" dir="rtl">{isolate(dir)}</span>}
          {f.uncommitted && <span className="shrink-0 rounded border border-border-strong px-1 text-[10px] text-subtle-foreground"
            data-testid="repo-uncommitted">{t("workbench.repoUncommitted")}</span>}
          {f.added != null && <span className="shrink-0 font-mono text-[11px]">
            <span className="text-success">+{f.added}</span> <span className="text-danger">−{f.removed}</span></span>}
        </>;
        const row = "flex w-full min-w-0 items-center gap-2 text-[12.5px]";
        return <li key={f.path} title={isolate(f.path)}>{opensDiff(f.path)
          ? <button type="button" className={`${row} -mx-1 rounded-md px-1 text-left hover:bg-foreground/[0.04]`} data-testid="repo-file-open"
            onClick={() => openReader({ kind: "repo-diff", conversationId, folder, path: f.path })}>
            {parts}<ChevronRight size={13} className="ml-auto shrink-0 text-subtle-foreground" aria-hidden /></button>
          : <div className={row}>{parts}</div>}</li>;
      })}</ul>}
      {repo.more > 0 && <p className="mt-0.5 text-[11px] text-subtle-foreground">{t("workbench.morePaths", { count: repo.more })}</p>}
    </div>
  );
}
