"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useProofJob, useProofJobPartitions, useProofs } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { ArrowLeft, Clock, Layers, Shield, Cpu } from "lucide-react";

const STATUS_VARIANTS: Record<
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

export default function ProofDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: job, isLoading } = useProofJob(taskId);
  const { data: partitions } = useProofJobPartitions(taskId);
  const { data: proofs } = useProofs(
    job ? { circuit_id: job.circuit_id, page: 1 } : undefined,
  );

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Link
          href="/proofs"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Proof Jobs
        </Link>
        <Card>
          <CardContent className="py-12 text-center text-gray-400">
            <p className="text-lg font-medium">Proof job not found</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const progress =
    job.num_partitions > 0
      ? Math.round((job.partitions_completed / job.num_partitions) * 100)
      : 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Back Link */}
      <Link
        href="/proofs"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Proof Jobs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight font-mono">
            {job.task_id}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Created {timeAgo(job.created_at)}
          </p>
        </div>
        <Badge variant={STATUS_VARIANTS[job.status] || "secondary"} className="text-sm">
          {job.status}
        </Badge>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={<Layers className="h-5 w-5 text-brand-600" />}
          title="Partitions"
          value={`${job.partitions_completed} / ${job.num_partitions}`}
        />
        <StatCard
          icon={<Shield className="h-5 w-5 text-purple-600" />}
          title="Redundancy"
          value={`${job.redundancy}x`}
        />
        <StatCard
          icon={<Clock className="h-5 w-5 text-yellow-600" />}
          title="Actual Time"
          value={job.actual_time_ms ? `${(job.actual_time_ms / 1000).toFixed(1)}s` : "—"}
        />
        <StatCard
          icon={<Cpu className="h-5 w-5 text-green-600" />}
          title="Circuit"
          value={
            <Link
              href={`/circuits/${job.circuit_id}`}
              className="text-brand-600 hover:underline"
            >
              #{job.circuit_id}
            </Link>
          }
        />
      </div>

      {/* Progress Bar */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 rounded-full bg-gray-100">
              <div
                className="h-3 rounded-full bg-brand-600 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="text-sm font-mono text-gray-600">{progress}%</span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4 text-sm text-gray-500">
            <div>
              <span className="font-medium text-gray-700">Witness CID:</span>
              <p className="font-mono text-xs mt-1 truncate">{job.witness_cid}</p>
            </div>
            <div>
              <span className="font-medium text-gray-700">Requester:</span>
              <p className="font-mono text-xs mt-1 truncate">
                {job.requester_hotkey}
              </p>
            </div>
            {job.estimated_time_ms && (
              <div>
                <span className="font-medium text-gray-700">Estimated Time:</span>
                <p className="font-mono text-xs mt-1">
                  {(job.estimated_time_ms / 1000).toFixed(1)}s
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Partitions Table */}
      {partitions && partitions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Partitions</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="px-4 py-3 font-medium">#</th>
                    <th className="px-4 py-3 font-medium">Constraints</th>
                    <th className="px-4 py-3 font-medium">Prover</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium text-right">Time</th>
                    <th className="px-4 py-3 font-medium">Fragment CID</th>
                  </tr>
                </thead>
                <tbody>
                  {partitions.map((p) => (
                    <tr
                      key={p.id}
                      className="border-b last:border-0 hover:bg-gray-50"
                    >
                      <td className="px-4 py-3 font-mono">
                        {p.partition_index}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {p.constraint_start}–{p.constraint_end}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {p.assigned_prover ? (
                          <Link
                            href={`/provers/${p.assigned_prover}`}
                            className="text-brand-600 hover:underline"
                          >
                            {p.assigned_prover.slice(0, 10)}...
                          </Link>
                        ) : (
                          <span className="text-gray-400">unassigned</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={STATUS_VARIANTS[p.status] || "secondary"}
                        >
                          {p.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {p.generation_time_ms
                          ? `${(p.generation_time_ms / 1000).toFixed(2)}s`
                          : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs truncate max-w-[200px]">
                        {p.proof_fragment_cid || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Generated Proofs */}
      {proofs?.items && proofs.items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Generated Proofs</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="px-4 py-3 font-medium">Proof Hash</th>
                    <th className="px-4 py-3 font-medium">GPU Backend</th>
                    <th className="px-4 py-3 font-medium text-right">
                      Gen Time
                    </th>
                    <th className="px-4 py-3 font-medium">Verified</th>
                    <th className="px-4 py-3 font-medium">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {proofs.items
                    .filter((p) => p.job_id === job.id)
                    .map((proof) => (
                      <tr
                        key={proof.id}
                        className="border-b last:border-0 hover:bg-gray-50"
                      >
                        <td className="px-4 py-3 font-mono text-xs truncate max-w-[200px]">
                          {proof.proof_hash}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary">
                            {proof.gpu_backend || "cpu"}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {(proof.generation_time_ms / 1000).toFixed(2)}s
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={proof.verified ? "success" : "warning"}
                          >
                            {proof.verified ? "verified" : "pending"}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-gray-500">
                          {timeAgo(proof.created_at)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
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
