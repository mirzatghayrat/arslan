/**
 * WB1 (user, 2026-10-30): the browser's address field also takes words. Words become a Bing search
 * (Bing is reachable without a VPN in more places than other engines); an address without a scheme
 * gets https://; an https:// address is kept. Any other scheme (http:, file:, javascript:, ...) is
 * refused with null, as the field only ever opened https:// pages. A Bing search is a plain GET, so it
 * fits the reader's no-forms rule; the server still checks every address it is asked to open.
 */
export const SEARCH_URL = "https://www.bing.com/search?q=";

export function addressOrSearch(raw: string): string | null {
  const input = raw.trim();
  if (!input) return null;
  if (/^https:\/\//i.test(input)) return input;
  if (/^[a-z][a-z0-9+.-]*:/i.test(input) && !/^[^\s/:]+\.[a-z]{2,}(:\d+)?([/?#]|$)/i.test(input)) return null;
  if (!/\s/.test(input) && /^[^\s/:]+\.[a-z]{2,}(:\d+)?([/?#].*)?$/i.test(input)) return `https://${input}`;
  return SEARCH_URL + encodeURIComponent(input);
}
