"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCircuit,
  useProofs,
  useRequestProof,
  type Circuit,
} from "@/lib/api";
import { formatNumber, timeAgo } from "@/lib/utils";
import {
  ArrowLeft,
  Cpu,
  Hash,
  Key,
  Layers,
  Zap,
  FileText,
} from "lucide-react";

export default function CircuitDetailPage() {
  const { id } = useParams<{ id: string }>();
  const circuitId = Number(id);
  const { data: circuit, isLoading } = useCircuit(circuitId);
  const { data: proofs } = useProofs({ circuit_id: circuitId, page: 1 });
  const [showProofForm, setShowProofForm] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (!circuit) {
    return (
      <div className="space-y-6 animate-fade-in">
        <Link
          href="/circuits"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Circuits
        </Link>
        <Card>
          <CardContent className="py-12 text-center text-gray-400">
            <p className="text-lg font-medium">Circuit not found</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Back Link */}
      <Link
        href="/circuits"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Circuits
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{circuit.name}</h1>
          <p className="mt-1 text-sm text-gray-500">
            v{circuit.version} · Published {timeAgo(circuit.created_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant="secondary">{circuit.proof_type}</Badge>
          <Badge variant="default">{circuit.circuit_type}</Badge>
        </div>
      </div>

      {/* Circuit Info Grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={<Layers className="h-5 w-5 text-brand-600" />}
          title="Constraints"
          value={formatNumber(circuit.num_constraints)}
        />
        <StatCard
          icon={<Zap className="h-5 w-5 text-green-600" />}
          title="Proofs Generated"
          value={formatNumber(circuit.proofs_generated)}
        />
        <StatCard
          icon={<Cpu className="h-5 w-5 text-purple-600" />}
          title="Proof System"
          value={circuit.proof_type.toUpperCase()}
        />
        <StatCard
          icon={<FileText className="h-5 w-5 text-yellow-600" />}
          title="Circuit Type"
          value={circuit.circuit_type}
        />
      </div>

      {/* Detail Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Circuit Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <DetailRow
            icon={<Hash className="h-4 w-4" />}
            label="Circuit Hash"
            value={circuit.circuit_hash}
            mono
          />
          <DetailRow
            icon={<Key className="h-4 w-4" />}
            label="IPFS CID"
            value={circuit.ipfs_cid}
            mono
          />
          {circuit.proving_key_cid && (
            <DetailRow
              icon={<Key className="h-4 w-4" />}
              label="Proving Key CID"
              value={circuit.proving_key_cid}
              mono
            />
          )}
          {circuit.verification_key_cid && (
            <DetailRow
              icon={<Key className="h-4 w-4" />}
              label="Verification Key CID"
              value={circuit.verification_key_cid}
              mono
            />
          )}
          <DetailRow
            icon={<Cpu className="h-4 w-4" />}
            label="Publisher"
            value={circuit.publisher_hotkey}
            mono
          />
        </CardContent>
      </Card>

      {/* Request Proof Form */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Request Proof</CardTitle>
            <Button
              size="sm"
              onClick={() => setShowProofForm(!showProofForm)}
            >
              {showProofForm ? "Cancel" : "New Proof Request"}
            </Button>
          </div>
        </CardHeader>
        {showProofForm && (
          <CardContent>
            <ProofRequestForm
              circuit={circuit}
              onSuccess={() => setShowProofForm(false)}
            />
          </CardContent>
        )}
      </Card>

      {/* Proofs Table */}
      {proofs?.items && proofs.items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Proofs ({proofs.total})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="px-4 py-3 font-medium">Proof Hash</th>
                    <th className="px-4 py-3 font-medium">Backend</th>
                    <th className="px-4 py-3 font-medium text-right">
                      Gen Time
                    </th>
                    <th className="px-4 py-3 font-medium">Verified</th>
                    <th className="px-4 py-3 font-medium">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {proofs.items.map((proof) => (
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
                        <Badge variant={proof.verified ? "success" : "warning"}>
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

function ProofRequestForm({
  circuit,
  onSuccess,
}: {
  circuit: Circuit;
  onSuccess: () => void;
}) {
  const requestProof = useRequestProof();
  const [witnessCid, setWitnessCid] = useState("");
  const [requesterHotkey, setRequesterHotkey] = useState("");
  const [numPartitions, setNumPartitions] = useState("4");
  const [redundancy, setRedundancy] = useState("2");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    requestProof.mutate(
      {
        circuit_id: circuit.id,
        witness_cid: witnessCid,
        requester_hotkey: requesterHotkey,
        num_partitions: Number(numPartitions),
        redundancy: Number(redundancy),
      },
      { onSuccess },
    );
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Witness Data CID
        </label>
        <input
          type="text"
          required
          value={witnessCid}
          onChange={(e) => setWitnessCid(e.target.value)}
          placeholder="QmXyz..."
          className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Requester Hotkey
        </label>
        <input
          type="text"
          required
          value={requesterHotkey}
          onChange={(e) => setRequesterHotkey(e.target.value)}
          placeholder="5..."
          className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Partitions
          </label>
          <input
            type="number"
            min="1"
            max="256"
            value={numPartitions}
            onChange={(e) => setNumPartitions(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Redundancy
          </label>
          <input
            type="number"
            min="1"
            max="10"
            value={redundancy}
            onChange={(e) => setRedundancy(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
      </div>
      <Button type="submit" disabled={requestProof.isPending}>
        {requestProof.isPending ? "Submitting..." : "Request Proof"}
      </Button>
      {requestProof.isError && (
        <p className="text-sm text-red-500">
          {requestProof.error.message}
        </p>
      )}
    </form>
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

function DetailRow({
  icon,
  label,
  value,
  mono = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 text-gray-400">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-gray-500">{label}</p>
        <p
          className={`mt-0.5 break-all ${mono ? "font-mono text-xs" : ""}`}
        >
          {value}
        </p>
      </div>
    </div>
  );
}
