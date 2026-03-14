/**
 * Typed API client for the Modelionn Registry backend.
 * All methods return typed responses; errors are thrown as ApiError.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public requestId?: string,
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (res.status === 429) {
      const retryAfter = res.headers.get("Retry-After") || "60";
      throw new ApiError(
        429,
        `Rate limit exceeded. Try again in ${retryAfter}s`,
        res.headers.get("x-request-id") || undefined,
      );
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(
        res.status,
        body.detail || body.message || res.statusText,
        res.headers.get("x-request-id") || undefined,
      );
    }

    // Handle 204 No Content
    if (res.status === 204) return undefined as T;
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

// ── Types ───────────────────────────────────────────────────

export interface Org {
  id: number;
  name: string;
  slug: string;
  created_at: string;
}

export interface OrgMember {
  user_id: number;
  hotkey: string;
  role: string;
  joined_at: string;
}

export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  key?: string;
  daily_limit: number;
  requests_today: number;
  created_at: string;
  revoked: boolean;
}

// ── ZK Proof Types ──────────────────────────────────────────

export interface Circuit {
  id: number;
  circuit_hash: string;
  name: string;
  version: string;
  proof_type: string;
  circuit_type: string;
  num_constraints: number;
  ipfs_cid: string;
  proving_key_cid?: string;
  verification_key_cid?: string;
  publisher_hotkey: string;
  proofs_generated: number;
  created_at: string;
}

export interface ProofJob {
  id: number;
  task_id: string;
  circuit_id: number;
  requester_hotkey: string;
  status: string;
  num_partitions: number;
  partitions_completed: number;
  redundancy: number;
  witness_cid: string;
  estimated_time_ms?: number;
  actual_time_ms?: number;
  created_at: string;
}

export interface ProofPartition {
  id: number;
  job_id: number;
  partition_index: number;
  constraint_start: number;
  constraint_end: number;
  assigned_prover?: string;
  status: string;
  proof_fragment_cid?: string;
  generation_time_ms?: number;
}

export interface Proof {
  id: number;
  proof_hash: string;
  circuit_id: number;
  job_id: number;
  proof_data_cid: string;
  generation_time_ms: number;
  gpu_backend?: string;
  verified: boolean;
  verified_by?: string;
  created_at: string;
}

export interface Prover {
  id: number;
  hotkey: string;
  gpu_name: string;
  gpu_backend: string;
  gpu_count: number;
  vram_bytes: number;
  benchmark_score: number;
  supported_proof_types: string;
  total_proofs: number;
  successful_proofs: number;
  failed_proofs: number;
  uptime_ratio: number;
  online: boolean;
  stake: number;
  last_seen: string;
}

export interface NetworkStats {
  total_provers: number;
  online_provers: number;
  total_proofs_generated: number;
  total_circuits: number;
  active_jobs: number;
  avg_proof_time_ms: number;
  total_gpu_vram_bytes: number;
}

export interface Webhook {
  id: number;
  url: string;
  label: string;
  events: string[];
  active: boolean;
  created_at: string;
  last_triggered_at: string | null;
}

// ── API Methods ─────────────────────────────────────────────

export const api = {
  // Health
  health: () => request<{ status: string; network: string }>("/health"),

  // Organizations
  listMyOrgs: () => request<Org[]>("/organizations/me"),

  getOrg: (slug: string) => request<Org>(`/orgs/${slug}`),

  createOrg: (body: { name: string; slug: string }) =>
    request<Org>("/orgs", { method: "POST", body: JSON.stringify(body) }),

  listOrgMembers: (slug: string, params?: { page?: number }) => {
    const qs = new URLSearchParams();
    qs.set("page", String(params?.page || 1));
    return request<{ items: OrgMember[]; total: number }>(
      `/orgs/${slug}/members?${qs}`,
    );
  },

  addOrgMember: (slug: string, body: { hotkey: string; role: string }) =>
    request<OrgMember>(
      `/orgs/${slug}/members?hotkey=${encodeURIComponent(body.hotkey)}&role=${encodeURIComponent(body.role)}`,
      {
        method: "POST",
      },
    ),

  removeOrgMember: (slug: string, hotkey: string) =>
    request<void>(`/orgs/${slug}/members/${hotkey}`, { method: "DELETE" }),

  // Search
  searchCircuits: (params: { q: string; page?: number }) => {
    const qs = new URLSearchParams();
    qs.set("search", params.q);
    qs.set("page", String(params.page || 1));
    return request<{ items: Circuit[]; total: number }>(`/circuits?${qs}`);
  },

  // API Keys
  listApiKeys: () => request<ApiKey[]>("/api-keys"),

  createApiKey: (body: { name: string; daily_limit?: number }) =>
    request<ApiKey>("/api-keys", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  revokeApiKey: (id: number) =>
    request<void>(`/api-keys/${id}`, { method: "DELETE" }),

  // ── ZK Proofs ───────────────────────────────────────────────

  // Circuits
  listCircuits: (params?: {
    proof_type?: string;
    circuit_type?: string;
    page?: number;
    page_size?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.proof_type) qs.set("proof_type", params.proof_type);
    if (params?.circuit_type) qs.set("circuit_type", params.circuit_type);
    qs.set("page", String(params?.page || 1));
    qs.set("page_size", String(params?.page_size || 20));
    return request<{ items: Circuit[]; total: number }>(`/circuits?${qs}`);
  },

  getCircuit: (circuitId: number) => request<Circuit>(`/circuits/${circuitId}`),

  uploadCircuit: (body: {
    name: string;
    version: string;
    proof_type: string;
    circuit_type: string;
    num_constraints: number;
    data_cid: string;
    proving_key_cid?: string;
    verification_key_cid?: string;
    publisher_hotkey: string;
  }) =>
    request<Circuit>("/circuits", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Proof Jobs
  requestProof: (body: {
    circuit_id: number;
    witness_cid: string;
    requester_hotkey: string;
    num_partitions?: number;
    redundancy?: number;
  }) =>
    request<ProofJob>("/proofs/jobs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProofJob: (taskId: string) => request<ProofJob>(`/proofs/jobs/${taskId}`),

  listProofJobs: (params?: { status?: string; page?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    qs.set("page", String(params?.page || 1));
    return request<{ items: ProofJob[]; total: number }>(`/proofs/jobs?${qs}`);
  },

  getProofJobPartitions: (taskId: string) =>
    request<ProofPartition[]>(`/proofs/jobs/${taskId}/partitions`),

  listProofs: (params?: {
    circuit_id?: number;
    verified?: boolean;
    page?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.circuit_id) qs.set("circuit_id", String(params.circuit_id));
    if (params?.verified !== undefined)
      qs.set("verified", String(params.verified));
    qs.set("page", String(params?.page || 1));
    return request<{ items: Proof[]; total: number }>(`/proofs?${qs}`);
  },

  verifyProof: (body: {
    proof_id: number;
    verification_key_cid: string;
    public_inputs_json?: string;
  }) =>
    request<{ valid: boolean; verification_time_ms: number }>(
      "/proofs/verify",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  // Provers (network nodes)
  listProvers: (params?: { online_only?: boolean; page?: number }) => {
    const qs = new URLSearchParams();
    if (params?.online_only) qs.set("online_only", "true");
    qs.set("page", String(params?.page || 1));
    return request<{ items: Prover[]; total: number }>(`/provers?${qs}`);
  },

  getProverStats: () => request<NetworkStats>("/provers/stats"),

  getProver: (hotkey: string) => request<Prover>(`/provers/${hotkey}`),

  // Webhooks
  listWebhooks: () => request<Webhook[]>("/webhooks"),

  createWebhook: (body: { url: string; label: string; events: string[] }) =>
    request<Webhook & { secret: string }>("/webhooks", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateWebhook: (
    id: number,
    body: { url?: string; label?: string; events?: string[]; active?: boolean },
  ) =>
    request<Webhook>(`/webhooks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteWebhook: (id: number) =>
    request<void>(`/webhooks/${id}`, { method: "DELETE" }),
};
