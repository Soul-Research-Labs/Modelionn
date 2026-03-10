"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useProver, useProofs } from "@/lib/api";
import { formatBytes, formatNumber, timeAgo } from "@/lib/utils";
import {
  ArrowLeft,
  Cpu,
  HardDrive,
  Zap,
  Clock,
  Activity,
  CheckCircle,
  XCircle,
} from "lucide-react";

export default function ProverDetailPage() {
  const { hotkey } = useParams<{ hotkey: string }>();
  const { data: prover, isLoading } = useProver(hotkey);

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (!prover) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Link
          href="/provers"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Prover Network
        </Link>
        <Card>
          <CardContent className="py-12 text-center text-gray-400">
            <p className="text-lg font-medium">Prover not found</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const successRate =
    prover.total_proofs > 0
      ? ((prover.successful_proofs / prover.total_proofs) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Back Link */}
      <Link
        href="/provers"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Prover Network
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight font-mono break-all">
            {prover.hotkey}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Last seen {timeAgo(prover.last_seen)}
          </p>
        </div>
        <Badge variant={prover.online ? "success" : "destructive"} className="text-sm">
          {prover.online ? "Online" : "Offline"}
        </Badge>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={<HardDrive className="h-5 w-5 text-brand-600" />}
          title="GPU"
          value={prover.gpu_name || "CPU"}
        />
        <StatCard
          icon={<Cpu className="h-5 w-5 text-purple-600" />}
          title="VRAM"
          value={formatBytes(prover.vram_bytes)}
        />
        <StatCard
          icon={<Activity className="h-5 w-5 text-yellow-600" />}
          title="Benchmark"
          value={prover.benchmark_score.toFixed(1)}
        />
        <StatCard
          icon={<Clock className="h-5 w-5 text-green-600" />}
          title="Uptime"
          value={`${(prover.uptime_ratio * 100).toFixed(1)}%`}
        />
      </div>

      {/* Hardware & Performance */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Hardware Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Hardware</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">GPU Model</span>
              <span className="font-medium">{prover.gpu_name || "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Backend</span>
              <Badge variant="secondary">{prover.gpu_backend}</Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">GPU Count</span>
              <span className="font-mono">{prover.gpu_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Total VRAM</span>
              <span className="font-mono">
                {formatBytes(prover.vram_bytes)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Supported Proof Types</span>
              <div className="flex gap-1">
                {prover.supported_proof_types.split(",").map((t) => (
                  <Badge key={t.trim()} variant="secondary" className="text-xs">
                    {t.trim()}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Performance */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Performance</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Benchmark Score</span>
              <span className="font-mono font-medium">
                {prover.benchmark_score.toFixed(1)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Total Proofs</span>
              <span className="font-mono">
                {formatNumber(prover.total_proofs)}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Successful</span>
              <span className="flex items-center gap-1 text-green-600 font-mono">
                <CheckCircle className="h-3.5 w-3.5" />
                {formatNumber(prover.successful_proofs)}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Failed</span>
              <span className="flex items-center gap-1 text-red-500 font-mono">
                <XCircle className="h-3.5 w-3.5" />
                {formatNumber(prover.failed_proofs)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Success Rate</span>
              <span className="font-mono font-medium">{successRate}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Stake</span>
              <span className="font-mono">
                {prover.stake.toFixed(4)} τ
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Uptime Bar */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Uptime</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 rounded-full bg-gray-100">
              <div
                className="h-3 rounded-full bg-green-500 transition-all"
                style={{ width: `${prover.uptime_ratio * 100}%` }}
              />
            </div>
            <span className="text-sm font-mono text-gray-600">
              {(prover.uptime_ratio * 100).toFixed(1)}%
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  icon,
  title,
  value,
}: {
  icon: React.ReactNode;
  title: string;
  value: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100">
          {icon}
        </div>
        <div>
          <p className="text-sm text-gray-500">{title}</p>
          <p className="text-xl font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}
