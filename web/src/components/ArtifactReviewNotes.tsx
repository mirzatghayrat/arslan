import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import type { ArtifactReview, StoredArtifact } from '../api/client.types';
import MarkdownLink from './MarkdownLink';

/**
 * Advisory source-review notes for one saved report snapshot (0.1.41).
 *
 * The review runs AFTER the report is saved and never blocked it. What it
 * found is model advice about absence/comparison claims, not a fact check,
 * and the panel says so every time it shows anything. Nothing renders when
 * the report was never reviewed (setting off, single-source, older version).
 */
export default function ArtifactReviewNotes({ file }: { file: StoredArtifact }) {
  const { t } = useTranslation();
  const [review, setReview] = useState<ArtifactReview | null>(null);

  useEffect(() => {
    let active = true;
    setReview(null);
    api.getArtifactReview(file.run_id, file.filename)
      .then(result => { if (active) setReview(result); })
      .catch(() => { if (active) setReview(null); });  // advice is optional; the report still shows
    return () => { active = false; };
  }, [file.run_id, file.filename, file.sha256]);

  // A note recorded for different bytes is not a note about this file.
  if (!review || review.status === 'none'
      || (review.artifact_sha256 && review.artifact_sha256 !== file.sha256)) return null;

  const issues = review.status === 'issues' ? review.issues ?? [] : [];
  return <section className="space-y-2 rounded-lg border border-border p-3 text-xs" data-testid="artifact-review">
    <h4 className="font-medium">{t('artifactReview.title')}</h4>
    <p className="text-muted-foreground">{t('artifactReview.disclaimer')}</p>
    {review.status === 'no_objection' && <p role="status">{t('artifactReview.noObjection')}</p>}
    {review.status === 'unavailable' && <p role="status" className="text-muted-foreground">{t('artifactReview.unavailable')}</p>}
    {issues.map((issue, index) => <div key={index} className="space-y-1 border-t border-border pt-2" data-testid="artifact-review-issue">
      <p className="flex items-start gap-1.5 text-warning"><AlertTriangle size={14} className="mt-[1px] shrink-0" aria-hidden />
        <span>{issue.reason}</span></p>
      <p><span className="text-muted-foreground">{t('artifactReview.draft')}</span> <q className="break-words">{issue.claim}</q></p>
      <p><span className="text-muted-foreground">{t('artifactReview.source')}</span> <q className="break-words">{issue.quote}</q></p>
      {/^https:\/\//.test(issue.source_url) && <MarkdownLink href={issue.source_url}>{t('artifactReview.openSource')}</MarkdownLink>}
    </div>)}
  </section>;
}
