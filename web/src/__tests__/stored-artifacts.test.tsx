import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ArtifactDownloads from '../components/ArtifactDownloads';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import { toUiMessages } from '../api/adapters';
import type { StoredArtifact } from '../api/client.types';

const { downloadRunArtifact } = vi.hoisted(() => ({ downloadRunArtifact: vi.fn() }));
vi.mock('../api/client', () => ({ api: { downloadRunArtifact } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
const file: StoredArtifact = { kind: 'file', run_id: 42, filename: 'run_42_abc_result.csv',
  title: 'result.csv', bytes: 9, sha256: 'hash', media_type: 'text/csv',
  url: 'https://untrusted.example/never-follow-this' };

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  downloadRunArtifact.mockReset();
});

describe('stored artifacts', () => {
  it('host result carries downloads and the Run link into the finished message', () => {
    const store = useArslanStore.getState();
    store.handleFrame({ type: 'stream_start', source: 'arslan', run_id: 42 });
    store.handleFrame({ type: 'tool_call', tool: 'run_python', args_summary: 'compute' });
    store.handleFrame({ type: 'tool_result', tool: 'run_python', ok: true, summary: 'saved', artifacts: [file] });
    store.handleFrame({ type: 'stream_chunk', content: 'done' });
    store.handleFrame({ type: 'stream_end', message_id: 5, run_id: 42 });
    const message = toUiMessages(useArslanStore.getState().items)[0];
    expect(message.runId).toBe(42);
    expect(message.toolActivity?.artifacts).toEqual([file]);
  });

  it('uses owner and filename, never the supplied URL; reports a failed download', async () => {
    downloadRunArtifact.mockRejectedValue(new Error('offline'));
    render(<ArtifactDownloads files={[file]} />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(downloadRunArtifact).toHaveBeenCalledWith(42, file.filename));
    expect(await screen.findByRole('alert')).toHaveTextContent('files.downloadFailed');
  });
});
