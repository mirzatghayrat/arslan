/**
 * Results from searching the brain through the agent's own retrieval pipeline.
 *
 * ONE BOX (decision 甲): typing filters the loaded tree, Enter runs the real
 * search. The two are different kinds of recall, so the panel says which one
 * produced what is on screen — merged into one control without that line, a
 * person cannot tell whether an absent result means "not in your memory" or
 * "not in the part already loaded".
 *
 * 🔴 NO RELEVANCE SCORES, and this is not a styling choice. `rerank` is lexical
 * overlap (CJK-aware), not semantic similarity. A 0.92 beside a row would be a
 * number the system cannot honestly produce, and it would be read as confidence
 * about meaning. The endpoint reports which pipeline ran; this renders that
 * sentence and nothing numeric.
 */
import { useTranslation } from 'react-i18next';

export interface BrainSearchHit {
  kind: string;
  ref: string;
  title: string;
  snippet: string;
}

interface Props {
  query: string;
  ranking: 'lexical' | 'hybrid';
  truncated: boolean;
  results: BrainSearchHit[];
  /** Currently hovered/selected hit, for the coordinated highlight. */
  focusedRef?: string | null;
  onHover: (kind: string, ref: string | null) => void;
  onOpen: (kind: string, ref: string) => void;
}

export default function BrainSearchResults(
  { query, ranking, truncated, results, focusedRef, onHover, onOpen }: Props,
) {
  const { t } = useTranslation();

  if (!query) return null;

  if (results.length === 0) {
    return (
      <div className="brain-search__panel" data-testid="brain-search-results">
        <p className="brain-search__empty">{t('brain.search_no_hits')}</p>
      </div>
    );
  }

  return (
    <div className="brain-search__panel" data-testid="brain-search-results">
      <div className="brain-search__head">
        <span>{t('brain.search_hits', { count: results.length })}</span>
        {/* Which pipeline ran, in words. Never a percentage. */}
        <span className="brain-search__ranking">
          {ranking === 'hybrid'
            ? t('brain.search_ranking_hybrid')
            : t('brain.search_ranking_lexical')}
        </span>
      </div>

      {results.map((hit) => (
        <div
          key={`${hit.kind}:${hit.ref}`}
          role="button"
          tabIndex={0}
          data-testid="brain-search-hit"
          className={`brain-search__row${focusedRef === hit.ref ? ' is-focused' : ''}`}
          onMouseEnter={() => onHover(hit.kind, hit.ref)}
          onMouseLeave={() => onHover(hit.kind, null)}
          onFocus={() => onHover(hit.kind, hit.ref)}
          onClick={() => onOpen(hit.kind, hit.ref)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') onOpen(hit.kind, hit.ref);
          }}
        >
          <div className="brain-search__title">
            {hit.title}
            <span className="brain-search__kind">{hit.kind}</span>
          </div>
          {hit.snippet && <div className="brain-search__snippet">{hit.snippet}</div>}
        </div>
      ))}

      {/* Capped results say so. A truncated list that stays quiet gets read as
          the complete answer — the same reason /brain/usage-events carries the
          flag rather than trimming in silence. */}
      {truncated && (
        <p className="brain-search__more">{t('brain.search_truncated')}</p>
      )}
    </div>
  );
}
