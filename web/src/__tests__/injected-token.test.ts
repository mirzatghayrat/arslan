import { beforeEach, describe, expect, it } from 'vitest';
import { bootstrapInjectedToken } from '../lib/injectedToken';
import { useAuthStore } from '../stores/authStore';

describe('desktop token bootstrap', () => {
  beforeEach(() => {
    delete window.__ARSLAN_TOKEN__;
    useAuthStore.getState().clearToken();
  });

  it('replaces a stale cached token with the current native token', () => {
    useAuthStore.getState().setToken('old-synthetic-token');
    window.__ARSLAN_TOKEN__ = 'new-synthetic-token';
    bootstrapInjectedToken();
    expect(useAuthStore.getState().token).toBe('new-synthetic-token');
    expect(localStorage.getItem('arslan_token')).toBe('new-synthetic-token');
  });

  it('hydrates an empty store', () => {
    window.__ARSLAN_TOKEN__ = ' current-synthetic-token ';
    bootstrapInjectedToken();
    expect(useAuthStore.getState().token).toBe('current-synthetic-token');
  });

  it.each([undefined, '', '   '])('preserves browser credentials without a usable native token: %s', (value) => {
    useAuthStore.getState().setToken('browser-synthetic-token');
    window.__ARSLAN_TOKEN__ = value;
    bootstrapInjectedToken();
    expect(useAuthStore.getState().token).toBe('browser-synthetic-token');
  });
});
