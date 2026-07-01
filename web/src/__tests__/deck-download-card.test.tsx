import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DeckDownloadCard from '../components/DeckDownloadCard';

describe('DeckDownloadCard', () => {
  beforeEach(() => {
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => 'blob:x');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
  });

  it('shows filename + slide count and downloads a pptx blob on click', () => {
    // a tiny valid base64 payload (content doesn't matter for the download path)
    const bytesB64 = btoa('PK\x03\x04 fake pptx bytes');
    render(<DeckDownloadCard filename="AI 2026.pptx" bytesB64={bytesB64} slides={7} />);
    expect(screen.getByText(/AI 2026\.pptx · 7 slides/)).toBeTruthy();

    fireEvent.click(screen.getByTitle(/download \.pptx/i));
    const createUrl = URL.createObjectURL as unknown as ReturnType<typeof vi.fn>;
    expect(createUrl).toHaveBeenCalledTimes(1);
    // it built a real Blob with the PPTX mime type
    const blob = createUrl.mock.calls[0][0] as Blob;
    expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.presentationml.presentation');
  });
});
