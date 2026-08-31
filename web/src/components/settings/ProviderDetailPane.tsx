/**
 * ProviderDetailPane — presentational right pane of the provider master-detail
 * layout (spec B2). Renders the fields + actions for the SELECTED saved config
 * OR the add-new draft.
 *
 * This component owns NO state, refs, or logic. Every ref invariant from the
 * Provider round (modelsFetchedRef / baseUrlDirtyRef / modelsEpochRef /
 * pendingCustomSwitchRef / health overlay / base_url blur-save) lives in the
 * container (ProviderConfigList). The pane only renders and calls the
 * passed-in callbacks. base_url still saves on BLUR only; the custom
 * quick-pick extras (chips + compat note + required hint) are rendered here
 * from a node the container builds.
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Star, Trash2, Loader2, FlaskConical, MoreHorizontal } from 'lucide-react';
import type { ModelInfo, ProviderOption, ProviderConfig } from '../../api/client.types';
import Select from '../Select';
import type { SelectOption } from '../Select';
import ModelCombobox from '../ModelCombobox';
import CapabilityBadges from './CapabilityBadges';
import ToolTransportWarning from './ToolTransportWarning';

const INPUT_CLS =
  'w-full bg-background border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-xl px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono';

/** Draft state for the add-new flow (owned by the container as state). */
export interface DraftConfig {
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  testState: 'idle' | 'testing' | 'ok' | 'failed';
  testError?: string;
}

export interface ProviderDetailPaneProps {
  llmProviders: ProviderOption[];
  providerSelectOptions: SelectOption[];
  // shared helpers (pure lookups from the container)
  isNative: (key: string) => boolean;
  baseUrlFor: (key: string) => string;
  staticModelInfos: (key: string) => ModelInfo[];

  // ── draft mode ──
  draft: DraftConfig | null;
  draftBusy: boolean;
  onDraftProviderChange: (key: string) => void;
  onDraftModelChange: (v: string) => void;
  onDraftBaseUrlChange: (v: string) => void;
  onDraftApiKeyChange: (v: string) => void;
  onDraftConfirm: () => void;
  onDraftCancel: () => void;
  draftCustomExtras: React.ReactNode;

  // ── config mode (selected saved config; null while drafting or empty) ──
  config: ProviderConfig | null;
  index: number;
  busy: number | null;
  onFieldChange: (
    config: ProviderConfig,
    field: 'provider' | 'model' | 'api_key',
    value: string,
  ) => void;
  onBaseUrlChange: (config: ProviderConfig, value: string) => void;
  onBaseUrlBlur: (config: ProviderConfig, value: string) => void;
  // ── saved-config API key (fresh-entry, decoupled from the masked server value) ──
  /** Local draft value for the selected config's key input (starts empty). */
  apiKeyDraft: string;
  onApiKeyDraftChange: (config: ProviderConfig, value: string) => void;
  /** Commit-on-blur: a non-empty draft persists as the NEW key, then clears. */
  onApiKeyDraftBlur: (config: ProviderConfig, value: string) => void;
  onSetPrimary: (id: number) => void;
  onDelete: (id: number) => void;
  registerBaseUrlRef: (id: number, el: HTMLInputElement | null) => void;
  modelOptions: ModelInfo[];
  modelStaleHint?: string;
  onModelFocus: () => void;
  onModelChange: (config: ProviderConfig, value: string) => void;
  onModelRefresh: () => void;
  showOllamaHint: boolean;
  configCustomExtras: React.ReactNode;

  // ── connection testing + capabilities (saved-config mode only) ──
  /** The one test: a real chat round-trip. There is no second, lesser test. */
  onTest: (config: ProviderConfig) => void;
  testStatus?: { state: 'idle' | 'testing' | 'ok' | 'failed'; error?: string; latency?: number };
  /** API-derived capabilities of the selected model (tools/vision/reasoning). */
  modelCapabilities: string[];
  onCapabilityOverride?: (cap: string, value: boolean) => void;
}

export default function ProviderDetailPane(props: ProviderDetailPaneProps) {
  const { t } = useTranslation();
  // Overflow menu for the rare + destructive actions (set primary / delete).
  const [moreOpen, setMoreOpen] = useState(false);
  const {
    providerSelectOptions,
    isNative,
    baseUrlFor,
    staticModelInfos,
    draft,
  } = props;

  // ── Draft (add-new) form ──────────────────────────────────────────────────
  if (draft) {
    return (
      <div
        data-testid="provider-detail-pane"
        className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-2 gap-3 items-start bg-surface border border-primary/30 rounded-xl px-4 py-4"
      >
        {/* Provider select */}
        <div className="min-w-0">
          <Select
            value={draft.provider}
            onChange={props.onDraftProviderChange}
            options={providerSelectOptions}
            ariaLabel="Provider"
          />
        </div>

        {/* Shown while choosing, not only after saving: the point is to catch
            someone before they pick a provider whose tools will never fire. */}
        <ToolTransportWarning provider={draft.provider} />

        {/* Model combobox (static seed options until the config is saved) */}
        <div className="min-w-0">
          <ModelCombobox
            data-testid="provider-draft-model"
            value={draft.model}
            onChange={props.onDraftModelChange}
            options={staticModelInfos(draft.provider)}
            ariaLabel="Model"
          />
        </div>

        {/* Base URL (non-native providers only) — part of the draft payload */}
        {!isNative(draft.provider) && (
          <div className="sm:col-span-2 min-w-0">
            <input
              type="text"
              data-testid="provider-draft-baseurl"
              value={draft.base_url}
              onChange={(e) => props.onDraftBaseUrlChange(e.target.value)}
              placeholder={baseUrlFor(draft.provider) || t('settings.labelBaseUrl')}
              aria-label={t('settings.labelBaseUrl')}
              className={INPUT_CLS}
            />
          </div>
        )}

        {/* API key */}
        <div className="sm:col-span-2 min-w-0">
          <input
            type="password"
            value={draft.api_key}
            onChange={(e) => props.onDraftApiKeyChange(e.target.value)}
            placeholder={t('settings.labelConfigApiKey')}
            className={INPUT_CLS}
          />
        </div>

        {/* Confirm / Cancel */}
        <div className="sm:col-span-2 flex items-center gap-2 flex-wrap pt-1 border-t border-border/40">
          <button
            type="button"
            data-testid="provider-draft-confirm"
            onClick={props.onDraftConfirm}
            disabled={
              !draft.provider ||
              !draft.model ||
              (draft.provider === 'custom' && !draft.base_url.trim()) ||
              props.draftBusy
            }
            className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-primary border border-primary/40 hover:border-primary/80 rounded-lg transition-colors disabled:opacity-30"
          >
            {t('settings.btnAddConfirm')}
          </button>
          <button
            type="button"
            onClick={props.onDraftCancel}
            className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-subtle-foreground hover:text-foreground border border-border hover:border-border-strong rounded-lg transition-colors"
          >
            {t('common.cancel')}
          </button>
        </div>

        {/* Add-flow error: a rejected addProviderConfig must surface here (never
            silent) so the draft stays open with an actionable reason. */}
        {draft.testState === 'failed' && draft.testError && (
          <p
            data-testid="provider-draft-error"
            className="w-full text-[10px] font-mono text-danger"
          >
            {draft.testError}
          </p>
        )}

        {/* P3: custom-provider extras (hint / quick-pick chips / compat note) */}
        {props.draftCustomExtras}
      </div>
    );
  }

  // ── Selected saved config ─────────────────────────────────────────────────
  const config = props.config;
  if (!config) {
    return (
      <div
        data-testid="provider-detail-empty"
        className="flex-1 min-w-0 flex items-center justify-center bg-surface/40 border border-dashed border-border rounded-xl px-4 py-8 text-xs font-mono text-subtle-foreground"
      >
        {t('settings.btnAddModel')}
      </div>
    );
  }

  const { index, busy } = props;
  const native = isNative(config.provider);

  return (
    <div
      data-testid="provider-detail-pane"
      className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-2 gap-3 items-start bg-surface border border-border rounded-xl px-4 py-4"
    >
      {/* Provider select */}
      <div className="min-w-0">
        <Select
          data-testid={`provider-config-provider-${index}`}
          id={`provider-config-provider-${index}`}
          value={config.provider}
          onChange={(v) => props.onFieldChange(config, 'provider', v)}
          options={providerSelectOptions}
          ariaLabel="Provider"
        />
      </div>

      <ToolTransportWarning provider={config.provider} />

      {/* Model combobox (dynamic catalog, lazy-fetched on first focus) */}
      <div className="min-w-0" onFocus={props.onModelFocus}>
        <ModelCombobox
          data-testid={`provider-config-model-${index}`}
          value={config.model}
          onChange={(v) => props.onModelChange(config, v)}
          options={props.modelOptions}
          staleHint={props.modelStaleHint}
          onRefresh={props.onModelRefresh}
          ariaLabel="Model"
        />
        {props.showOllamaHint && (
          <p
            data-testid={`provider-config-ollama-hint-${index}`}
            className="mt-1 text-[10px] font-mono text-subtle-foreground"
          >
            {t('settings.ollamaNotDetected')}{' '}
            <a
              href="https://ollama.com/download"
              target="_blank"
              rel="noreferrer"
              className="underline text-primary hover:text-primary/80"
            >
              {t('settings.ollamaDownload')}
            </a>
          </p>
        )}
        {/* Spans BOTH grid columns: the chips were wrapping onto a second row
            because they lived inside one half of a 2-column grid. That is what
            made this block read as cramped. */}
        <div className="sm:col-span-2 min-w-0">
        <CapabilityBadges
          configId={config.id}
          model={config.model}
          capabilities={props.modelCapabilities}
          onOverride={props.onCapabilityOverride}
        />
        </div>
      </div>

      {/* Base URL (non-native providers only) — saved on blur */}
      {!native && (
        <div className="sm:col-span-2 min-w-0">
          <input
            type="text"
            ref={(el) => {
              props.registerBaseUrlRef(config.id, el);
            }}
            data-testid={`provider-config-baseurl-${index}`}
            value={config.base_url}
            onChange={(e) => props.onBaseUrlChange(config, e.target.value)}
            onBlur={(e) => props.onBaseUrlBlur(config, e.target.value)}
            placeholder={baseUrlFor(config.provider) || t('settings.labelBaseUrl')}
            aria-label={t('settings.labelBaseUrl')}
            className={INPUT_CLS}
          />
        </div>
      )}

      {/* API key — a FRESH-ENTRY field, deliberately decoupled from the masked
          server value. The input starts empty (local draft) and commits the
          NEW typed value on BLUR (mirrors base_url's blur-save). Placeholder +
          the inline status line are driven by the honest key_status so an
          undecryptable key (ARSLAN_SECRET_KEY changed) never reads as a plain
          "requires API key". */}
      <div className="sm:col-span-2 min-w-0">
        {/* The backend has always sent a masked form of the stored key
            (mask_secret → "sk-…1a4f"); the UI dropped it and showed an empty
            password box, which reads as "nothing configured here" — the most
            common reason someone replaces a key that was already fine. */}
        {config.key_status === 'set' && !props.apiKeyDraft && config.api_key && (
          <div
            data-testid={`provider-config-key-masked-${index}`}
            className="mb-1.5 flex items-center gap-2 text-[11px] font-mono text-muted-foreground"
          >
            <span className="tracking-wider">{config.api_key}</span>
            <span className="text-subtle-foreground">·</span>
            <span className="text-[10px] text-subtle-foreground">
              {t('settings.keyTypeToReplace')}
            </span>
          </div>
        )}
        <input
          type="password"
          data-testid={`provider-config-key-${index}`}
          value={props.apiKeyDraft}
          onChange={(e) => props.onApiKeyDraftChange(config, e.target.value)}
          onBlur={(e) => props.onApiKeyDraftBlur(config, e.target.value)}
          placeholder={
            config.key_status === 'set'
              ? t('settings.keySavedReplace')
              : config.key_status === 'undecryptable'
                ? t('settings.keyReenter')
                : t('settings.keyEnter')
          }
          className={INPUT_CLS}
        />
        {config.key_status === 'undecryptable' && (
          <p
            data-testid={`provider-config-key-undecryptable-${index}`}
            className="mt-1 text-[10px] font-mono text-danger"
          >
            {t('settings.keyUndecryptableReason')}
          </p>
        )}
      </div>

      {/* Actions, as one row across the full width rather than three loose grid
          cells. Test is the only thing anyone comes here to press, so it is the
          only thing that looks like a button; setting the primary and deleting
          live behind the overflow — they are rare, and one is destructive.

          There used to be TWO tests here: a "Test connection" that asked the
          model-list endpoint, and a "Deep test" that sent a real message. Only
          the second answered the question anyone actually has, and the first was
          the one that lit up green — so the pair was worse than either alone. */}
      <div className="sm:col-span-2 flex items-center gap-2 pt-3 mt-1 border-t border-border">
        <button
          type="button"
          data-testid={`provider-config-test-${index}`}
          onClick={() => props.onTest(config)}
          disabled={props.testStatus?.state === 'testing'}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-[11px] font-mono font-medium text-primary-foreground bg-primary hover:bg-primary-hover rounded-lg transition-colors disabled:opacity-60"
        >
          {props.testStatus?.state === 'testing' ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <FlaskConical className="w-3 h-3" />
          )}
          {t('settings.btnTest')}
        </button>

        {/* Round-trip time. It answers what the pill cannot: not "does it work"
            but "how slow is it" — how you tell a healthy local model from one
            that will make every turn feel broken. */}
        {props.testStatus?.state === 'ok' && props.testStatus.latency != null && (
          <span
            data-testid={`provider-config-latency-${index}`}
            className="text-[10px] font-mono text-muted-foreground"
          >
            · {props.testStatus.latency}ms
          </span>
        )}

        <span className="flex-1" />

        <div className="relative">
          <button
            type="button"
            data-testid={`provider-config-more-${index}`}
            aria-haspopup="menu"
            aria-expanded={moreOpen}
            aria-label={t('common.more')}
            onClick={() => setMoreOpen((o) => !o)}
            className="px-2 py-1.5 text-subtle-foreground hover:text-foreground hover:bg-surface-raised rounded-lg transition-colors"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>
          {moreOpen && (
            <div
              role="menu"
              data-testid={`provider-config-more-menu-${index}`}
              className="absolute right-0 bottom-full mb-1 w-44 bg-surface border border-border-strong rounded-xl p-1 shadow-lg z-40"
            >
              {!config.is_primary && (
                <button
                  type="button"
                  role="menuitem"
                  data-testid={`provider-config-primary-${index}`}
                  onClick={() => {
                    props.onSetPrimary(config.id);
                    setMoreOpen(false);
                  }}
                  disabled={busy === config.id}
                  className="w-full flex items-center gap-2 px-2.5 py-2 text-[11px] font-mono text-muted-foreground hover:text-primary hover:bg-surface-raised rounded-lg transition-colors disabled:opacity-50"
                >
                  <Star className="w-3 h-3" />
                  {t('settings.btnSetPrimary')}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                data-testid={`provider-config-delete-${index}`}
                onClick={() => {
                  props.onDelete(config.id);
                  setMoreOpen(false);
                }}
                disabled={busy === config.id || config.is_primary}
                title={config.is_primary ? t('settings.deletePrimaryBlocked') : undefined}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-[11px] font-mono text-subtle-foreground hover:text-danger hover:bg-danger/5 rounded-lg transition-colors disabled:opacity-30"
              >
                <Trash2 className="w-3 h-3" />
                {t('settings.btnDelete')}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* P3: custom-provider extras (hint / quick-pick chips / compat note) */}
      {props.configCustomExtras}
    </div>
  );
}
