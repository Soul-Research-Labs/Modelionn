"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCircuits } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Cpu, Upload } from "lucide-react";
import Link from "next/link";

export default function CircuitsPage() {
  const { data: circuits, isLoading } = useCircuits({ page: 1, page_size: 20 });

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Circuits</h1>
          <p className="mt-1 text-gray-500">
            ZK circuits available for proof generation
          </p>
        </div>
        <Button>
          <Upload className="mr-2 h-4 w-4" />
          Upload Circuit
        </Button>
      </div>

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
