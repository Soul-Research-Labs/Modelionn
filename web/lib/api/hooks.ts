import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

// ── Health ──────────────────────────────────────────────────

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.health(),
    refetchInterval: 30_000,
  });
}

// ── API Keys ────────────────────────────────────────────────

export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api.listApiKeys(),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
    onError: (error: Error) => {
      console.error("Create API key failed:", error.message);
    },
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.revokeApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
    onError: (error: Error) => {
      console.error("Revoke API key failed:", error.message);
    },
  });
}

// ── ZK Circuits ─────────────────────────────────────────────

export function useCircuits(params?: {
  proof_type?: string;
  circuit_type?: string;
  page?: number;
  page_size?: number;
}) {
  return useQuery({
    queryKey: ["circuits", params],
    queryFn: () => api.listCircuits(params),
  });
}

export function useCircuit(circuitId: number) {
  return useQuery({
    queryKey: ["circuit", circuitId],
    queryFn: () => api.getCircuit(circuitId),
    enabled: circuitId > 0,
  });
}

export function useUploadCircuit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.uploadCircuit,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["circuits"] }),
    onError: (error: Error) => {
      console.error("Upload circuit failed:", error.message);
    },
  });
}

// ── ZK Proof Jobs ───────────────────────────────────────────

export function useProofJobs(params?: { status?: string; page?: number }) {
  return useQuery({
    queryKey: ["proofJobs", params],
    queryFn: () => api.listProofJobs(params),
    refetchInterval: 10_000,
  });
}

export function useProofJob(taskId: string) {
  return useQuery({
    queryKey: ["proofJob", taskId],
    queryFn: () => api.getProofJob(taskId),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && (data.status === "completed" || data.status === "failed"))
        return false;
      return 3000;
    },
  });
}

export function useProofJobPartitions(taskId: string) {
  return useQuery({
    queryKey: ["proofJobPartitions", taskId],
    queryFn: () => api.getProofJobPartitions(taskId),
    enabled: !!taskId,
    refetchInterval: 5_000,
  });
}

export function useRequestProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.requestProof,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proofJobs"] }),
    onError: (error: Error) => {
      console.error("Request proof failed:", error.message);
    },
  });
}

export function useProofs(params?: {
  circuit_id?: number;
  verified?: boolean;
  page?: number;
}) {
  return useQuery({
    queryKey: ["proofs", params],
    queryFn: () => api.listProofs(params),
  });
}

export function useVerifyProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.verifyProof,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proofs"] }),
    onError: (error: Error) => {
      console.error("Verify proof failed:", error.message);
    },
  });
}

// ── ZK Provers (Network) ────────────────────────────────────

export function useProvers(params?: { online_only?: boolean; page?: number }) {
  return useQuery({
    queryKey: ["provers", params],
    queryFn: () => api.listProvers(params),
    refetchInterval: 15_000,
  });
}

export function useNetworkStats() {
  return useQuery({
    queryKey: ["networkStats"],
    queryFn: () => api.getProverStats(),
    refetchInterval: 15_000,
  });
}

export function useProver(hotkey: string) {
  return useQuery({
    queryKey: ["prover", hotkey],
    queryFn: () => api.getProver(hotkey),
    enabled: !!hotkey,
  });
}

// ── Organizations ───────────────────────────────────────────

export function useMyOrgs() {
  return useQuery({
    queryKey: ["myOrgs"],
    queryFn: () => api.listMyOrgs(),
  });
}

export function useOrg(slug: string) {
  return useQuery({
    queryKey: ["org", slug],
    queryFn: () => api.getOrg(slug),
    enabled: !!slug,
  });
}

export function useCreateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createOrg,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["myOrgs"] }),
  });
}

export function useOrgMembers(slug: string, page?: number) {
  return useQuery({
    queryKey: ["orgMembers", slug, page],
    queryFn: () => api.listOrgMembers(slug, { page }),
    enabled: !!slug,
  });
}

export function useAddOrgMember(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { hotkey: string; role: string }) =>
      api.addOrgMember(slug, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orgMembers", slug] }),
  });
}

export function useRemoveOrgMember(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (hotkey: string) => api.removeOrgMember(slug, hotkey),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orgMembers", slug] }),
  });
}

// ── Search ──────────────────────────────────────────────────

export function useSearchCircuits(q: string, page?: number) {
  return useQuery({
    queryKey: ["searchCircuits", q, page],
    queryFn: () => api.searchCircuits({ q, page }),
    enabled: q.length > 0,
  });
}

// ── Webhooks ────────────────────────────────────────────────

export function useWebhooks() {
  return useQuery({
    queryKey: ["webhooks"],
    queryFn: () => api.listWebhooks(),
  });
}

export function useCreateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createWebhook,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

export function useUpdateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; url?: string; label?: string; events?: string[]; active?: boolean }) =>
      api.updateWebhook(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

export function useDeleteWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteWebhook,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}
