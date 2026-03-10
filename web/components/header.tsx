"use client";

import { useSession, signIn, signOut } from "next-auth/react";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function Header() {
  const { data: session } = useSession();
  const router = useRouter();
  const [query, setQuery] = useState("");

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      router.push(`/search?q=${encodeURIComponent(query.trim())}`);
    }
  };

  return (
    <header className="flex h-16 items-center justify-between border-b border-gray-200 bg-white px-6">
      {/* Search bar */}
      <form
        onSubmit={handleSearch}
        className="flex w-full max-w-md items-center"
        role="search"
        aria-label="Search proofs and circuits"
      >
        <div className="relative w-full">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
            aria-hidden="true"
          />
          <input
            type="search"
            placeholder="Search circuits, proofs, provers..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search circuits, proofs, and provers"
            className="w-full rounded-lg border border-gray-200 bg-surface-1 py-2 pl-10 pr-4 text-sm text-gray-700 placeholder-gray-400 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100 transition-colors"
          />
        </div>
      </form>

      {/* Auth */}
      <div className="ml-4 flex items-center gap-3">
        {session ? (
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600 font-medium">
              {session.user?.name || "Wallet Connected"}
            </span>
            <button
              onClick={() => signOut()}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Sign Out
            </button>
          </div>
        ) : (
          <button
            onClick={() => signIn()}
            className="rounded-lg bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 transition-colors"
          >
            Connect Wallet
          </button>
        )}
      </div>
    </header>
  );
}
