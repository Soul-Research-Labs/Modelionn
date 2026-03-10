"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useProofJobs } from "@/lib/api";
import { Zap, Plus } from "lucide-react";
import Link from "next/link";

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

export default function ProofsPage() {
  const { data: jobs, isLoading } = useProofJobs({ page: 1 });

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Proof Jobs</h1>
          <p className="mt-1 text-gray-500">
            Track ZK proof generation across the network
          </p>
        </div>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Request Proof
        </Button>
      </div>

      {/* Status Filters */}
      <div className="flex gap-2">
        {["all", "queued", "proving", "completed", "failed"].map((s) => (
          <Badge
            key={s}
            variant={
              s === "all" ? "default" : STATUS_VARIANTS[s] || "secondary"
            }
            className="cursor-pointer"
          >
            {s === "all" ? "All" : s}
          </Badge>
        ))}
      </div>

      {isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : jobs?.items && jobs.items.length > 0 ? (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="px-4 py-3 font-medium">Task ID</th>
                    <th className="px-4 py-3 font-medium">Circuit</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium text-center">
                      Progress
                    </th>
                    <th className="px-4 py-3 font-medium text-right">
                      Redundancy
                    </th>
                    <th className="px-4 py-3 font-medium text-right">Time</th>
                    <th className="px-4 py-3 font-medium">Requester</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.items.map((job) => {
                    const progress =
                      job.num_partitions > 0
                        ? Math.round(
                            (job.partitions_completed / job.num_partitions) *
                              100,
                          )
                        : 0;
                    return (
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
                        <td className="px-4 py-3">#{job.circuit_id}</td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={STATUS_VARIANTS[job.status] || "secondary"}
                          >
                            {job.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="h-2 flex-1 rounded-full bg-gray-100">
                              <div
                                className="h-2 rounded-full bg-brand-600 transition-all"
                                style={{ width: `${progress}%` }}
                              />
                            </div>
                            <span className="text-xs text-gray-500">
                              {job.partitions_completed}/{job.num_partitions}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {job.redundancy}x
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {job.actual_time_ms
                            ? `${(job.actual_time_ms / 1000).toFixed(1)}s`
                            : "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {job.requester_hotkey.slice(0, 10)}...
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-12 text-center text-gray-400">
            <Zap className="mx-auto mb-4 h-12 w-12" />
            <p className="text-lg font-medium">No proof jobs yet</p>
            <p className="mt-1">Request a proof to see it tracked here</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
