/**
 * The diagnosis of why stored secrets cannot be read, as the backend reports it.
 *
 * WHY A VERDICT AND NOT A SENTENCE. This replaces
 * `settings.keyUndecryptableReason`, which said the stored key could not be
 * decrypted "because ARSLAN_SECRET_KEY changed". In the incident that produced this
 * whole change ARSLAN_SECRET_KEY had NOT changed — the PBKDF2 salt had, when the data
 * directory moved. The sentence was specific, credible and wrong, so its reader went
 * and checked the one half that was fine. A backend that cannot know the cause must
 * not hard-code one; it computes a verdict, and the words live here, per verdict.
 *
 * See server/services/crypto_boot.py: diagnose(), GET /settings/crypto-health.
 */

/** Must stay identical to `VERDICTS` in server/services/crypto_boot.py. */
export type CryptoVerdict =
  | 'healthy'
  | 'secret-missing'
  | 'recoverable'
  | 'salt-lost'
  | 'secret-does-not-match';

export interface CryptoHealth {
  verdict: CryptoVerdict;
  /** How many stored values cannot be opened. Never the values themselves. */
  undecryptable: number;
  /** How many of those a candidate salt could open. */
  recoverable: number;
  salt_provenance: string | null;
}

/**
 * Verdict → locale key. One paragraph per verdict, deliberately.
 *
 * If two verdicts ever shared a string the diagnosis would be decoration: the whole
 * point is that "the salt is missing" and "this secret is not the one that wrote
 * these" send the reader to different places. A test asserts the rendered words
 * differ, not merely that the keys do.
 */
export const VERDICT_COPY_KEY = {
  'healthy': 'cryptoHealthHealthy',
  'secret-missing': 'cryptoHealthSecretMissing',
  'recoverable': 'cryptoHealthRecoverable',
  'salt-lost': 'cryptoHealthSaltLost',
  'secret-does-not-match': 'cryptoHealthMismatch',
} as const satisfies Record<CryptoVerdict, string>;

/** True when the user needs to be told something. `healthy` says nothing at all. */
export function needsCryptoNotice(health: CryptoHealth | null): boolean {
  return health !== null && health.verdict !== 'healthy';
}

/**
 * How loud to be. `recoverable` is amber rather than red on purpose: a way back
 * exists, and dressing it identically to permanent loss would misprice it.
 */
export function cryptoNoticeTone(verdict: CryptoVerdict): 'danger' | 'warning' {
  return verdict === 'recoverable' || verdict === 'secret-missing' ? 'warning' : 'danger';
}
