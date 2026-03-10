import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import crypto from "crypto";

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

        // Basic validation — hotkey should be an ss58 address (starts with 5, 48 chars)
        if (!hotkey.startsWith("5") || hotkey.length < 40) {
          return null;
        }

        // Verify nonce is recent (within 5 minutes)
        const nonceTime = parseInt(nonce, 10);
        const now = Math.floor(Date.now() / 1000);
        if (isNaN(nonceTime) || Math.abs(now - nonceTime) > 300) {
          return null;
        }

        // Dev fallback: verify sha256 signature
        const expectedSig = crypto
          .createHash("sha256")
          .update(`${hotkey}:${nonce}`)
          .digest("hex");

        if (signature !== expectedSig) {
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
