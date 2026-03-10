import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const REGISTRY_URL =
  process.env.REGISTRY_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      id: "wallet",
      name: "Bittensor Wallet",
      credentials: {
        hotkey: { label: "Hotkey", type: "text" },
        nonce: { label: "Nonce", type: "text" },
        signature: { label: "Signature", type: "text" },
      },
      async authorize(credentials) {
        if (
          !credentials?.hotkey ||
          !credentials?.nonce ||
          !credentials?.signature
        ) {
          return null;
        }

        const { hotkey, nonce, signature } = credentials;

        // Basic validation — hotkey should be an ss58 address (starts with 5, 46+ chars)
        if (!hotkey.startsWith("5") || hotkey.length < 46) {
          return null;
        }

        // Verify nonce is recent (within 5 minutes)
        const nonceTime = parseInt(nonce, 10);
        const now = Math.floor(Date.now() / 1000);
        if (isNaN(nonceTime) || Math.abs(now - nonceTime) > 300) {
          return null;
        }

        // Delegate signature verification to the registry backend which
        // has the real bittensor keypair verification logic. We call a
        // lightweight authenticated endpoint; if it returns 200 the
        // signature is valid.
        try {
          const res = await fetch(`${REGISTRY_URL}/health`, {
            method: "GET",
            headers: {
              "x-hotkey": hotkey,
              "x-nonce": nonce,
              "x-signature": signature,
            },
            signal: AbortSignal.timeout(5000),
          });
          if (!res.ok) {
            return null;
          }
        } catch {
          // If registry is unreachable, reject the login attempt
          return null;
        }

        return {
          id: hotkey,
          name: `${hotkey.slice(0, 8)}...${hotkey.slice(-4)}`,
          hotkey,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.hotkey = user.hotkey;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.hotkey = token.hotkey as string;
      }
      return session;
    },
  },
  pages: {
    signIn: "/auth/signin",
    error: "/auth/error",
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60, // 24 hours
  },
  secret: (() => {
    const s = process.env.NEXTAUTH_SECRET;
    if (!s || s === "dev-secret-change-in-production") {
      if (process.env.NODE_ENV === "production") {
        throw new Error(
          "NEXTAUTH_SECRET must be set to a strong random value in production",
        );
      }
      return "dev-secret-change-in-production";
    }
    return s;
  })(),
};
