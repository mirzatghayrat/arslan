/** Never trust that a value in UI state was already masked by the server.
 * Short keys are hidden entirely; longer values reveal at most their suffix.
 * This is display-only and must never be used as the credential sent to an API.
 */
export function maskSecretForDisplay(value: string): string {
  if (!value) return '';
  return value.length > 8 ? `•••• ${value.slice(-4)}` : '••••';
}
