"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
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

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-64 flex-shrink-0 border-r border-gray-200 bg-surface-1 md:flex md:flex-col">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2 border-b border-gray-200 px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white font-bold text-sm">
          M
        </div>
        <span className="text-lg font-semibold tracking-tight">ZKML</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-4" aria-label="Main navigation">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-100 text-brand-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-gray-200 p-4">
        <p className="text-xs text-gray-400">ZKML v0.2.0</p>
        <p className="text-xs text-gray-400">ZK Prover Network on Bittensor</p>
      </div>
    </aside>
  );
}
