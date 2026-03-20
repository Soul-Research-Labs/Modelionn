"use client";

import { Suspense, useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isDevelopmentAuth, signWithDevAuth } from "@/lib/auth-dev";

function SignInPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";
  const [hotkey, setHotkey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hotkey.trim()) return;

    setLoading(true);
    setError("");

    const nonce = Math.floor(Date.now() / 1000).toString();

    let signature: string;
    try {
      if (isDevelopmentAuth()) {
        // Development-only: SHA-256(hotkey:nonce) with runtime safety checks
        signature = await signWithDevAuth(hotkey, nonce);
      } else {
        // Production: require real Bittensor wallet signing via browser extension
        setLoading(false);
        setError(
          "Wallet signing required. Install the Bittensor wallet extension or enable NEXT_PUBLIC_DEV_AUTH for development.",
        );
        return;
      }
    } catch (err) {
      setLoading(false);
      setError(
        err instanceof Error
          ? err.message
          : "Signing failed. Please try again.",
      );
      return;
    }

    const result = await signIn("wallet", {
      hotkey,
      nonce,
      signature,
      redirect: false,
      callbackUrl,
    });

    setLoading(false);

    if (result?.ok) {
      router.push(callbackUrl);
    } else {
      setError("Authentication failed. Please check your hotkey.");
    }
  };

  return (
    <div className="flex min-h-[60vh] items-center justify-center animate-fade-in">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-white font-bold text-xl">
            M
          </div>
          <CardTitle className="text-2xl">Sign in to ZKML</CardTitle>
          <p className="mt-2 text-sm text-gray-500">
            Connect your Bittensor wallet to access the registry
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="hotkey"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Hotkey (SS58 Address)
              </label>
              <input
                id="hotkey"
                type="text"
                value={hotkey}
                onChange={(e) => setHotkey(e.target.value)}
                placeholder="5GrwvaHF..."
                className="w-full rounded-lg border border-gray-200 bg-surface-1 px-4 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 transition-colors"
                required
                autoComplete="off"
              />
            </div>
            {error && (
              <p className="text-sm text-red-600" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Connecting..." : "Connect Wallet"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <SignInPageContent />
    </Suspense>
  );
}
