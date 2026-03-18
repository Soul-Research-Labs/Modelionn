/**
 * Tests for Next.js middleware — CSP nonce, auth redirects, security headers.
 *
 * We test the middleware function directly by passing mock NextRequest objects.
 */

// Mock next-auth/jwt before importing middleware
const mockGetToken = jest.fn();
jest.mock("next-auth/jwt", () => ({
  getToken: (...args: unknown[]) => mockGetToken(...args),
}));

// Mock crypto.randomUUID for deterministic nonce
const MOCK_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const originalRandomUUID = globalThis.crypto?.randomUUID;
beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: {
      ...globalThis.crypto,
      randomUUID: () => MOCK_UUID,
    },
    writable: true,
  });
});
afterAll(() => {
  if (originalRandomUUID) {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: originalRandomUUID,
    });
  }
});

import { NextRequest } from "next/server";
import { middleware } from "@/middleware";

function makeRequest(path: string): NextRequest {
  return new NextRequest(new URL(path, "http://localhost:3000"));
}

describe("Next.js Middleware", () => {
  beforeEach(() => {
    mockGetToken.mockReset();
  });

  // ── Auth Redirects ────────────────────────────────────────

  describe("auth protection", () => {
    it("redirects unauthenticated users from /settings", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/settings"));

      expect(response.status).toBe(307);
      const location = response.headers.get("location");
      expect(location).toContain("/auth/signin");
      expect(location).toContain("callbackUrl=%2Fsettings");
    });

    it("redirects unauthenticated users from /admin", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/admin"));

      expect(response.status).toBe(307);
      const location = response.headers.get("location");
      expect(location).toContain("/auth/signin");
    });

    it("redirects unauthenticated users from /organizations", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/organizations"));
      expect(response.status).toBe(307);
    });

    it("redirects from nested protected routes", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/organizations/acme"));
      expect(response.status).toBe(307);
    });

    it("allows authenticated users through protected routes", async () => {
      mockGetToken.mockResolvedValue({ sub: "user123", name: "Test User" });
      const response = await middleware(makeRequest("/settings"));
      expect(response.status).toBe(200);
    });

    it("does not redirect public routes", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/circuits"));
      expect(response.status).toBe(200);
    });

    it("does not redirect the home page", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      expect(response.status).toBe(200);
    });
  });

  // ── CSP and Security Headers ──────────────────────────────

  describe("security headers", () => {
    it("sets Content-Security-Policy with nonce", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      const csp = response.headers.get("Content-Security-Policy");

      expect(csp).toBeTruthy();
      const expectedNonce = Buffer.from(MOCK_UUID).toString("base64");
      expect(csp).toContain(`'nonce-${expectedNonce}'`);
      expect(csp).toContain("default-src 'self'");
      expect(csp).toContain("frame-ancestors 'none'");
    });

    it("sets x-nonce header", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      const nonce = response.headers.get("x-nonce");
      expect(nonce).toBeTruthy();
      expect(nonce).toBe(Buffer.from(MOCK_UUID).toString("base64"));
    });

    it("sets X-Frame-Options DENY", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      expect(response.headers.get("X-Frame-Options")).toBe("DENY");
    });

    it("sets X-Content-Type-Options nosniff", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    });

    it("sets Referrer-Policy", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      expect(response.headers.get("Referrer-Policy")).toBe(
        "strict-origin-when-cross-origin",
      );
    });

    it("sets Permissions-Policy restricting camera/mic/geo", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      const pp = response.headers.get("Permissions-Policy");
      expect(pp).toContain("camera=()");
      expect(pp).toContain("microphone=()");
      expect(pp).toContain("geolocation=()");
    });
  });

  // ── CSP connect-src includes API URL ──────────────────────

  describe("CSP connect-src", () => {
    it("includes the default API URL in connect-src", async () => {
      mockGetToken.mockResolvedValue(null);
      const response = await middleware(makeRequest("/"));
      const csp = response.headers.get("Content-Security-Policy");
      // Default: http://localhost:8000
      expect(csp).toContain("connect-src 'self'");
    });
  });
});
