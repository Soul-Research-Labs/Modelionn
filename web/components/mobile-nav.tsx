"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";
import {
  LayoutDashboard,
  Cpu,
  Zap,
  Network,
  Settings,
  Building2,
  Search,
  Trophy,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/provers", label: "Prover Network", icon: Network },
  { href: "/leaderboard", label: "Leaderboard", icon: Trophy },
  { href: "/circuits", label: "Circuits", icon: Cpu },
  { href: "/proofs", label: "Proof Jobs", icon: Zap },
  { href: "/organizations", label: "Organizations", icon: Building2 },
  { href: "/search", label: "Search", icon: Search },
  { href: "/admin", label: "Admin", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function MobileNav({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 data-[state=open]:animate-fade-in" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-gray-900 shadow-xl data-[state=open]:animate-fade-in focus:outline-none">
          {/* Header */}
          <div className="flex h-16 items-center justify-between border-b border-gray-200 dark:border-gray-700 px-6">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white font-bold text-sm">
                M
              </div>
              <span className="text-lg font-semibold tracking-tight dark:text-white">
                ZKML
              </span>
            </div>
            <Dialog.Close asChild>
              <button
                className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
                aria-label="Close navigation"
              >
                <X className="h-5 w-5" />
              </button>
            </Dialog.Close>
          </div>

          {/* Navigation */}
          <nav className="flex-1 space-y-1 p-4" aria-label="Mobile navigation">
            {navItems.map((item) => {
              const isActive =
                pathname === item.href ||
                (item.href !== "/" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onClose}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-brand-100 text-brand-700 dark:bg-brand-900/30 dark:text-brand-400"
                      : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200",
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="border-t border-gray-200 dark:border-gray-700 p-4">
            <p className="text-xs text-gray-400">ZKML v0.2.0</p>
            <p className="text-xs text-gray-400">
              ZK Prover Network on Bittensor
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
