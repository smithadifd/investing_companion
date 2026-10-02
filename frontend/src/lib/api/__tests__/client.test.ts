import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../client';

const ApiClient = api.constructor as new () => typeof api;

const ACCESS_TOKEN_KEY = 'investing_companion_access_token';
const REFRESH_TOKEN_KEY = 'investing_companion_refresh_token';

class MockStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

function getRefreshToken(client: unknown): string | null {
  if (client && typeof client === 'object' && 'refreshToken' in client) {
    const token = client.refreshToken;
    return typeof token === 'string' ? token : null;
  }
  return null;
}

describe('ApiClient localStorage guards', () => {
  const originalDescriptor =
    Object.getOwnPropertyDescriptor(window, 'localStorage') ||
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(window), 'localStorage');

  let mockStorage: MockStorage;

  beforeEach(() => {
    vi.restoreAllMocks();
    mockStorage = new MockStorage();
    Object.defineProperty(window, 'localStorage', {
      value: mockStorage,
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    if (originalDescriptor) {
      Object.defineProperty(window, 'localStorage', originalDescriptor);
    } else {
      delete (window as unknown as { localStorage?: unknown }).localStorage;
    }
  });

  describe('constructor read', () => {
    it('loads stored tokens when localStorage is working', () => {
      window.localStorage.setItem(ACCESS_TOKEN_KEY, 'stored-access-token');
      window.localStorage.setItem(REFRESH_TOKEN_KEY, 'stored-refresh-token');

      const client = new ApiClient();

      expect(client.getAccessToken()).toBe('stored-access-token');
      expect(client.isAuthenticated()).toBe(true);
      expect(getRefreshToken(client)).toBe('stored-refresh-token');
    });

    it('does not throw and leaves in-memory tokens null when localStorage is undefined', () => {
      Object.defineProperty(window, 'localStorage', {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(typeof window).toBe('object');
      expect(typeof window.localStorage).toBe('undefined');

      let client!: typeof api;
      expect(() => {
        client = new ApiClient();
      }).not.toThrow();

      expect(client.getAccessToken()).toBeNull();
      expect(client.isAuthenticated()).toBe(false);
      expect(getRefreshToken(client)).toBeNull();
    });
  });

  describe('storeTokens via login()', () => {
    const mockLoginResponse = {
      data: {
        access_token: 'login-access-token',
        refresh_token: 'login-refresh-token',
        token_type: 'bearer',
      },
    };

    it('stores tokens in localStorage and in memory when localStorage is working', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(mockLoginResponse), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const client = new ApiClient();
      const tokens = await client.login({
        email: 'test@example.com',
        password: 'password123',
      });

      expect(tokens.access_token).toBe('login-access-token');
      expect(tokens.refresh_token).toBe('login-refresh-token');

      // Working localStorage assertions: values are written
      expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('login-access-token');
      expect(window.localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('login-refresh-token');

      // In-memory state updated
      expect(client.getAccessToken()).toBe('login-access-token');
      expect(client.isAuthenticated()).toBe(true);
      expect(getRefreshToken(client)).toBe('login-refresh-token');
    });

    it('does not throw and updates in-memory tokens when localStorage is undefined', async () => {
      Object.defineProperty(window, 'localStorage', {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(typeof window).toBe('object');
      expect(typeof window.localStorage).toBe('undefined');

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(mockLoginResponse), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const client = new ApiClient();
      const tokens = await client.login({
        email: 'test@example.com',
        password: 'password123',
      });

      expect(tokens.access_token).toBe('login-access-token');
      expect(tokens.refresh_token).toBe('login-refresh-token');

      // In-memory state updated without throw
      expect(client.getAccessToken()).toBe('login-access-token');
      expect(client.isAuthenticated()).toBe(true);
      expect(getRefreshToken(client)).toBe('login-refresh-token');
    });
  });

  describe('clearTokens via logout()', () => {
    it('removes tokens from localStorage and clears in-memory tokens when localStorage is working', async () => {
      const client = new ApiClient();

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              access_token: 'active-access-token',
              refresh_token: 'active-refresh-token',
              token_type: 'bearer',
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      );

      await client.login({
        email: 'test@example.com',
        password: 'password123',
      });

      expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('active-access-token');
      expect(window.localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('active-refresh-token');
      expect(client.isAuthenticated()).toBe(true);

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify({ message: 'Logged out' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      await client.logout();

      // Working localStorage assertions: values are removed
      expect(window.localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
      expect(window.localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();

      // In-memory state cleared
      expect(client.getAccessToken()).toBeNull();
      expect(client.isAuthenticated()).toBe(false);
      expect(getRefreshToken(client)).toBeNull();

      // Refresh token revocation was attempted
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/auth/logout'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ refresh_token: 'active-refresh-token' }),
        })
      );
    });

    it('does not throw and clears in-memory tokens when localStorage is undefined', async () => {
      Object.defineProperty(window, 'localStorage', {
        value: undefined,
        configurable: true,
        writable: true,
      });

      expect(typeof window).toBe('object');
      expect(typeof window.localStorage).toBe('undefined');

      const client = new ApiClient();

      // Set in-memory tokens via login with mock response
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              access_token: 'session-access-token',
              refresh_token: 'session-refresh-token',
              token_type: 'bearer',
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      );

      await client.login({
        email: 'test@example.com',
        password: 'password123',
      });

      expect(client.isAuthenticated()).toBe(true);
      expect(client.getAccessToken()).toBe('session-access-token');

      // Logout with undefined localStorage
      const logoutSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify({ message: 'Logged out' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      await expect(client.logout()).resolves.toBeUndefined();

      // In-memory state cleared without throw
      expect(client.getAccessToken()).toBeNull();
      expect(client.isAuthenticated()).toBe(false);
      expect(getRefreshToken(client)).toBeNull();

      expect(logoutSpy).toHaveBeenCalledWith(
        expect.stringContaining('/auth/logout'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ refresh_token: 'session-refresh-token' }),
        })
      );
    });
  });
});
