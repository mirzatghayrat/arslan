import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AttachBar from "../components/AttachBar";

vi.mock("../api/client", () => ({
  api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() },
}));
import { api } from "../api/client";
const m = api as unknown as { extractAttachmentFile: any; extractAttachmentUrl: any };

describe("AttachBar", () => {
  beforeEach(() => vi.clearAllMocks());

  it("extracts a URL and shows a chip + reports via onChange", async () => {
    m.extractAttachmentUrl.mockResolvedValue({ text: "body", chars: 4, truncated: false });
    const onChange = vi.fn();
    render(<AttachBar onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/网址|http/i), { target: { value: "https://x.com" } });
    fireEvent.click(screen.getByText("读取"));
    await waitFor(() => expect(m.extractAttachmentUrl).toHaveBeenCalledWith("https://x.com", false));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ name: "https://x.com", text: "body", chars: 4, truncated: false }),
    ]));
  });

  it("removes a chip and reports empty via onChange", async () => {
    m.extractAttachmentUrl.mockResolvedValue({ text: "body", chars: 4, truncated: false });
    const onChange = vi.fn();
    render(<AttachBar onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/网址|http/i), { target: { value: "https://x.com" } });
    fireEvent.click(screen.getByText("读取"));
    await screen.findByLabelText("remove-attachment");
    fireEvent.click(screen.getByLabelText("remove-attachment"));
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([]));
  });

  it("surfaces an extract error without crashing", async () => {
    m.extractAttachmentUrl.mockRejectedValue(new Error("extract failed: 400"));
    render(<AttachBar onChange={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/网址|http/i), { target: { value: "http://169.254.169.254" } });
    fireEvent.click(screen.getByText("读取"));
    await waitFor(() => expect(screen.getByText(/extract failed/i)).toBeInTheDocument());
  });
});
