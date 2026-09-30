import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
// The proactivity cause-guess limit (0.1.47) sits in Automation and loads its own config; this
// file is about another control, so it is stubbed rather than given a backend.
vi.mock("../components/settings/ProactiveDiagnosisCap", () => ({ default: () => null }));
vi.mock("../api/client", () => ({ api: { getArtifactReview: vi.fn() } }));

import { api } from "../api/client";
import ArtifactReviewNotes from "../components/ArtifactReviewNotes";
import AutomationSection from "../components/settings/AutomationSection";
import type { StoredArtifact } from "../api/client.types";

const file: StoredArtifact = {
  kind: "file", run_id: 7, filename: "run_7_abc_report.md", title: "report.md",
  bytes: 5, sha256: "a".repeat(64), media_type: "text/markdown", url: "/api/v1/runs/7/artifacts/run_7_abc_report.md",
};
const issue = {
  claim: "The English README lacks a local-run section.", quote: "Run it locally with",
  reason: "The English README does describe running locally.", source_id: "source:x",
  source_url: "https://example.org/README.md",
};
const review = vi.mocked(api.getArtifactReview);

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("ArtifactReviewNotes", () => {
  it("shows each anchored issue with the disclaimer and a gated source link", async () => {
    review.mockResolvedValue({ status: "issues", issues: [issue], artifact_sha256: file.sha256 });
    render(<ArtifactReviewNotes file={file} />);
    expect(await screen.findByTestId("artifact-review-issue")).toBeInTheDocument();
    expect(screen.getByText("artifactReview.disclaimer")).toBeInTheDocument();
    expect(screen.getByText(issue.reason)).toBeInTheDocument();
    expect(screen.getByText(issue.claim)).toBeInTheDocument();
    expect(screen.getByText(issue.quote)).toBeInTheDocument();
    expect(screen.getByText("artifactReview.openSource").closest("a")).toHaveAttribute("href", issue.source_url);
    expect(review).toHaveBeenCalledWith(7, "run_7_abc_report.md");
  });

  it("renders nothing for a report that was never reviewed", async () => {
    review.mockResolvedValue({ status: "none" });
    const { container } = render(<ArtifactReviewNotes file={file} />);
    await waitFor(() => expect(review).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("never shows a note recorded for different bytes", async () => {
    review.mockResolvedValue({ status: "issues", issues: [issue], artifact_sha256: "b".repeat(64) });
    const { container } = render(<ArtifactReviewNotes file={file} />);
    await waitFor(() => expect(review).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("states a finished review with no findings, and an unfinished one, without inventing issues", async () => {
    review.mockResolvedValue({ status: "no_objection", issues: [], artifact_sha256: file.sha256 });
    render(<ArtifactReviewNotes file={file} />);
    expect(await screen.findByText("artifactReview.noObjection")).toBeInTheDocument();
    cleanup();
    review.mockResolvedValue({ status: "unavailable", code: "research_review_unavailable", artifact_sha256: file.sha256 });
    render(<ArtifactReviewNotes file={file} />);
    expect(await screen.findByText("artifactReview.unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("artifact-review-issue")).toBeNull();
  });

  it("does not render a non-HTTPS source as a link", async () => {
    review.mockResolvedValue({ status: "issues", artifact_sha256: file.sha256,
      issues: [{ ...issue, source_url: "javascript:alert(1)" }] });
    render(<ArtifactReviewNotes file={file} />);
    await screen.findByTestId("artifact-review-issue");
    expect(screen.queryByText("artifactReview.openSource")).toBeNull();
  });

  it("keeps the report usable when the note cannot be loaded", async () => {
    review.mockRejectedValue(new Error("offline"));
    const { container } = render(<ArtifactReviewNotes file={file} />);
    await waitFor(() => expect(review).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("research review setting", () => {
  it("is off by default, carries its spend note, and reports changes", () => {
    const onChange = vi.fn();
    render(<AutomationSection curationEnabled={false}
      heartbeatEnabled={false} heartbeatChecklist="" onResearchReviewEnabledChange={onChange} />);
    const toggle = screen.getByTestId("research-review-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(screen.getByTestId("research-review-spend-note")).toHaveTextContent("settings.researchReviewSpendNote");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
