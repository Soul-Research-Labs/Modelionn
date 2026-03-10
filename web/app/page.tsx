"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useHealth,
  useNetworkStats,
  useProofJobs,
  useProvers,
} from "@/lib/api";
import { formatNumber, formatBytes } from "@/lib/utils";
import {
  Package,
  Download,
  Trophy,
  Activity,
  ArrowRight,
  Cpu,
  Zap,
  Network,
  Clock,
} from "lucide-react";
import Link from "next/link";

export default function HomePage() {
  const { data: health } = useHealth();
  const { data: networkStats } = useNetworkStats();
  const { data: proofJobs } = useProofJobs({ page: 1 });
  const { data: provers } = useProvers({ online_only: true, page: 1 });

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Hero */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-gray-500">
          GPU-Accelerated ZK Prover Network on Bittensor
        </p>
      </div>

      {/* Network KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title="Online Provers"
          value={networkStats?.online_provers ?? provers?.total ?? "—"}
          icon={<Network className="h-5 w-5 text-brand-600" />}
          subtitle={
            networkStats ? `${networkStats.total_provers} total` : undefined
          }
        />
        <KPICard
          title="Proofs Generated"
          value={
            networkStats
              ? formatNumber(networkStats.total_proofs_generated)
              : "—"
          }
          icon={<Zap className="h-5 w-5 text-green-600" />}
        />
        <KPICard
          title="Circuits"
          value={networkStats?.total_circuits ?? "—"}
          icon={<Cpu className="h-5 w-5 text-purple-600" />}
        />
        <KPICard
          title="Avg Proof Time"
          value={
            networkStats?.avg_proof_time_ms
              ? `${(networkStats.avg_proof_time_ms / 1000).toFixed(1)}s`
              : "—"
          }
          icon={<Clock className="h-5 w-5 text-yellow-600" />}
          subtitle={
            networkStats ? `${networkStats.active_jobs} active jobs` : undefined
          }
        />
      </div>

      {/* GPU Network Summary */}
      {networkStats && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Network className="h-5 w-5" />
              Network Overview
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <div>
                <p className="text-sm text-gray-500">Total GPU VRAM</p>
                <p className="text-xl font-bold">
                  {formatBytes(networkStats.total_gpu_vram_bytes)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Online Provers</p>
                <p className="text-xl font-bold">
                  {networkStats.online_provers}/{networkStats.total_provers}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Active Jobs</p>
                <p className="text-xl font-bold">{networkStats.active_jobs}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Health</p>
                <p className="text-xl font-bold">
                  <Badge
                    variant={health?.status === "ok" ? "default" : "secondary"}
                  >
                    {health?.status === "ok" ? "Healthy" : "Unknown"}
                  </Badge>
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Proof Jobs */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold">Recent Proof Jobs</h2>
          <Link href="/proofs">
            <Button variant="ghost" size="sm">
              View all <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </Link>
        </div>
        {proofJobs?.items && proofJobs.items.length > 0 ? (
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="px-4 py-3 font-medium">Job ID</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Partitions</th>
                    <th className="px-4 py-3 font-medium text-right">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {proofJobs.items.slice(0, 5).map((job) => (
                    <tr
                      key={job.task_id}
                      className="border-b last:border-0 hover:bg-gray-50"
                    >
                      <td className="px-4 py-3 font-mono text-xs">
                        <Link
                          href={`/proofs/${job.task_id}`}
                          className="text-brand-600 hover:underline"
                        >
                          {job.task_id.slice(0, 12)}...
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        <ProofStatusBadge status={job.status} />
                      </td>
                      <td className="px-4 py-3">
                        {job.partitions_completed}/{job.num_partitions}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {job.actual_time_ms
                          ? `${(job.actual_time_ms / 1000).toFixed(1)}s`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-8 text-center text-gray-400">
              No proof jobs yet. Submit a circuit to get started.
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function KPICard({
  title,
  value,
  icon,
  subtitle,
}: {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  subtitle?: string;
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
          {subtitle && <p className="text-xs text-gray-400">{subtitle}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function ProofStatusBadge({ status }: { status: string }) {
  const variants: Record<
    string,
    "default" | "secondary" | "success" | "destructive" | "warning"
  > = {
    queued: "secondary",
    partitioning: "secondary",
    dispatched: "warning",
    proving: "warning",
    aggregating: "warning",
    verifying: "warning",
    completed: "success",
    failed: "destructive",
    timeout: "destructive",
  };
  return <Badge variant={variants[status] || "secondary"}>{status}</Badge>;
}
