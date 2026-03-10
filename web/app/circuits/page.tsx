"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCircuits, useUploadCircuit } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Cpu, Upload, X } from "lucide-react";
import Link from "next/link";

export default function CircuitsPage() {
  const { data: circuits, isLoading } = useCircuits({ page: 1, page_size: 20 });
  const [showUpload, setShowUpload] = useState(false);

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Circuits</h1>
          <p className="mt-1 text-gray-500">
            ZK circuits available for proof generation
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)}>
          <Upload className="mr-2 h-4 w-4" />
          Upload Circuit
        </Button>
      </div>

      {/* Upload Modal */}
      {showUpload && (
        <UploadCircuitModal onClose={() => setShowUpload(false)} />
      )}

      {/* Filter Chips */}
      <div className="flex gap-2">
        {["groth16", "plonk", "halo2", "stark"].map((ps) => (
          <Badge key={ps} variant="secondary" className="cursor-pointer">
            {ps.toUpperCase()}
          </Badge>
        ))}
        <span className="mx-2 text-gray-300">|</span>
        {["general", "evm", "zkml", "custom"].map((ct) => (
          <Badge key={ct} variant="secondary" className="cursor-pointer">
            {ct}
          </Badge>
        ))}
      </div>

      {/* Circuit Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-48 rounded-xl" />
          ))}
        </div>
      ) : circuits?.items && circuits.items.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {circuits.items.map((c) => (
            <Link key={c.id} href={`/circuits/${c.id}`}>
              <Card className="h-full transition-shadow hover:shadow-md cursor-pointer">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <Badge variant="secondary">{c.proof_type}</Badge>
                    <Badge variant="default">{c.circuit_type}</Badge>
                  </div>
                  <CardTitle className="mt-2 text-base">{c.name}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm text-gray-500">
                    <div className="flex justify-between">
                      <span>Constraints</span>
                      <span className="font-mono">
                        {formatNumber(c.num_constraints)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Proofs Generated</span>
                      <span className="font-mono">
                        {formatNumber(c.proofs_generated)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Version</span>
                      <span>{c.version}</span>
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-gray-400 font-mono truncate">
                    {c.circuit_hash}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-12 text-center text-gray-400">
            <Cpu className="mx-auto mb-4 h-12 w-12" />
            <p className="text-lg font-medium">No circuits uploaded yet</p>
            <p className="mt-1">Upload a circuit to start generating proofs</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function UploadCircuitModal({ onClose }: { onClose: () => void }) {
  const uploadCircuit = useUploadCircuit();
  const [form, setForm] = useState({
    name: "",
    version: "1.0.0",
    proof_type: "groth16",
    circuit_type: "general",
    num_constraints: "",
    data_cid: "",
    proving_key_cid: "",
    verification_key_cid: "",
    publisher_hotkey: "",
  });

  const update = (field: string, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    uploadCircuit.mutate(
      {
        name: form.name,
        version: form.version,
        proof_type: form.proof_type,
        circuit_type: form.circuit_type,
        num_constraints: Number(form.num_constraints),
        data_cid: form.data_cid,
        proving_key_cid: form.proving_key_cid || undefined,
        verification_key_cid: form.verification_key_cid || undefined,
        publisher_hotkey: form.publisher_hotkey,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-full max-w-lg mx-4">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Upload Circuit</CardTitle>
            <button
              onClick={onClose}
              className="rounded-full p-1 hover:bg-gray-100"
            >
              <X className="h-5 w-5 text-gray-500" />
            </button>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="my-circuit"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Version
                </label>
                <input
                  type="text"
                  required
                  value={form.version}
                  onChange={(e) => update("version", e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Proof Type
                </label>
                <select
                  value={form.proof_type}
                  onChange={(e) => update("proof_type", e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                >
                  <option value="groth16">Groth16</option>
                  <option value="plonk">PLONK</option>
                  <option value="halo2">Halo2</option>
                  <option value="stark">STARK</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Circuit Type
                </label>
                <select
                  value={form.circuit_type}
                  onChange={(e) => update("circuit_type", e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                >
                  <option value="general">General</option>
                  <option value="evm">EVM</option>
                  <option value="zkml">ZKML</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Number of Constraints
              </label>
              <input
                type="number"
                required
                min="1"
                value={form.num_constraints}
                onChange={(e) => update("num_constraints", e.target.value)}
                placeholder="1000000"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Circuit Data CID (IPFS)
              </label>
              <input
                type="text"
                required
                value={form.data_cid}
                onChange={(e) => update("data_cid", e.target.value)}
                placeholder="QmXyz..."
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Proving Key CID
                  <span className="text-gray-400 ml-1">(optional)</span>
                </label>
                <input
                  type="text"
                  value={form.proving_key_cid}
                  onChange={(e) => update("proving_key_cid", e.target.value)}
                  placeholder="QmXyz..."
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Verification Key CID
                  <span className="text-gray-400 ml-1">(optional)</span>
                </label>
                <input
                  type="text"
                  value={form.verification_key_cid}
                  onChange={(e) =>
                    update("verification_key_cid", e.target.value)
                  }
                  placeholder="QmXyz..."
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Publisher Hotkey
              </label>
              <input
                type="text"
                required
                value={form.publisher_hotkey}
                onChange={(e) => update("publisher_hotkey", e.target.value)}
                placeholder="5..."
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div className="flex gap-3 pt-2">
              <Button type="submit" disabled={uploadCircuit.isPending}>
                {uploadCircuit.isPending ? "Uploading..." : "Upload Circuit"}
              </Button>
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
            </div>
            {uploadCircuit.isError && (
              <p className="text-sm text-red-500">
                {uploadCircuit.error.message}
              </p>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
