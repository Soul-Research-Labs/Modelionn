"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useProvers, useNetworkStats } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/utils";
import { Network, Cpu, Zap, HardDrive } from "lucide-react";
import Link from "next/link";

export default function ProversPage() {
  const { data: stats, isLoading: loadingStats } = useNetworkStats();
  const { data: provers, isLoading: loadingProvers } = useProvers({
    page: 1,
  });

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Prover Network</h1>
        <p className="mt-1 text-gray-500">
          GPU-accelerated nodes generating ZK proofs
        </p>
      </div>

      {/* Network Stats */}
      {loadingStats ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Online Provers"
            value={`${stats.online_provers}/${stats.total_provers}`}
            icon={<Network className="h-5 w-5 text-brand-600" />}
          />
          <StatCard
            title="Total Proofs"
            value={formatNumber(stats.total_proofs_generated)}
            icon={<Zap className="h-5 w-5 text-green-600" />}
          />
          <StatCard
            title="Total GPU VRAM"
            value={formatBytes(stats.total_gpu_vram_bytes)}
            icon={<HardDrive className="h-5 w-5 text-purple-600" />}
          />
          <StatCard
            title="Avg Proof Time"
            value={`${(stats.avg_proof_time_ms / 1000).toFixed(1)}s`}
            icon={<Cpu className="h-5 w-5 text-yellow-600" />}
          />
        </div>
      ) : null}

      {/* Prover List */}
      <section>
        <h2 className="mb-4 text-xl font-semibold">Provers</h2>
        {loadingProvers ? (
          <Skeleton className="h-64 rounded-xl" />
        ) : (
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="px-4 py-3 font-medium">Hotkey</th>
                      <th className="px-4 py-3 font-medium">GPU</th>
                      <th className="px-4 py-3 font-medium">Backend</th>
                      <th className="px-4 py-3 font-medium text-right">VRAM</th>
                      <th className="px-4 py-3 font-medium text-right">
                        Benchmark
                      </th>
                      <th className="px-4 py-3 font-medium text-right">
                        Proofs
                      </th>
                      <th className="px-4 py-3 font-medium text-right">
                        Uptime
                      </th>
                      <th className="px-4 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {provers?.items.map((p) => (
                      <tr
                        key={p.hotkey}
                        className="border-b last:border-0 hover:bg-gray-50"
                      >
                        <td className="px-4 py-3 font-mono text-xs">
                          <Link
                            href={`/provers/${p.hotkey}`}
                            className="text-brand-600 hover:underline"
                          >
                            {p.hotkey.slice(0, 10)}...
                          </Link>
                        </td>
                        <td className="px-4 py-3">{p.gpu_name || "CPU"}</td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary">{p.gpu_backend}</Badge>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {formatBytes(p.vram_bytes)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {p.benchmark_score.toFixed(1)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <span className="text-green-600">
                            {p.successful_proofs}
                          </span>
                          /
                          <span className="text-red-500">
                            {p.failed_proofs}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {(p.uptime_ratio * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={p.online ? "success" : "destructive"}>
                            {p.online ? "Online" : "Offline"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function StatCard({
  title,
  value,
  icon,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100">
          {icon}
        </div>
        <div>
          <p className="text-sm text-gray-500">{title}</p>
          <p className="text-2xl font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}
