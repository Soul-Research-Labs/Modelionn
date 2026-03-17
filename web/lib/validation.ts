import { z } from "zod";

/** SS58 hotkey — alphanumeric starting with 5, 48 chars */
const ss58Hotkey = z
  .string()
  .min(1, "Hotkey is required")
  .regex(
    /^5[A-Za-z0-9]{47}$/,
    "Must be a valid SS58 hotkey (starts with 5, 48 chars)",
  );

/** Artifact name — alphanumeric with hyphens */
const artifactName = z
  .string()
  .min(1, "Name is required")
  .max(128, "Name too long")
  .regex(/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/, "Invalid artifact name");

/** Version string */
const version = z
  .string()
  .min(1, "Version is required")
  .max(64, "Version too long");

export const evalFormSchema = z.object({
  artifact_name: artifactName,
  artifact_version: version,
  submitter_hotkey: ss58Hotkey,
});

const ipfsCid = z
  .string()
  .min(1, "CID is required")
  .regex(/^(Qm[1-9A-HJ-NP-Za-km-z]{44}|bafy[a-z0-9]+)$/i, "Invalid IPFS CID");

export const orgFormSchema = z.object({
  name: z.string().min(1, "Organization name is required").max(256, "Name too long"),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(128, "Slug too long")
    .regex(/^[a-z0-9-]+$/, "Slug must contain lowercase letters, numbers, and hyphens only"),
});

export const circuitUploadSchema = z.object({
  name: artifactName,
  version,
  proof_type: z.enum(["groth16", "plonk", "halo2", "stark"]),
  circuit_type: z.enum(["general", "evm", "zkml", "custom"]),
  num_constraints: z.number().int("Constraints must be a whole number").positive("Constraints must be greater than zero"),
  data_cid: ipfsCid,
  proving_key_cid: ipfsCid.optional(),
  verification_key_cid: ipfsCid.optional(),
  publisher_hotkey: ss58Hotkey,
});

export const webhookFormSchema = z.object({
  url: z
    .string()
    .min(1, "Webhook URL is required")
    .url("Must be a valid URL")
    .startsWith("https://", "Webhook URL must use HTTPS")
    .max(2048, "URL too long"),
  label: z.string().min(1, "Label is required").max(256, "Label too long"),
  events: z
    .array(z.string())
    .min(1, "At least one event must be selected")
    .refine((events) => {
      const allowed = new Set([
        "*",
        "proof.completed",
        "proof.failed",
        "circuit.uploaded",
        "prover.online",
        "prover.offline",
      ]);
      return events.every((e) => allowed.has(e));
    }, "Invalid event type selected"),
});

export const apiKeyFormSchema = z.object({
  name: z.string().min(1, "API key name is required").max(256, "Name too long"),
  daily_limit: z
    .number()
    .int("Must be a whole number")
    .positive("Daily limit must be positive")
    .max(1000000, "Daily limit too high"),
});

export const notificationFormSchema = z.object({
  channel_type: z.enum(["slack", "discord"]),
  webhook_url: z
    .string()
    .url("Must be a valid URL")
    .startsWith("https://", "Webhook URL must use HTTPS"),
});

export const searchFormSchema = z.object({
  query: z.string().max(256, "Search query too long"),
});

export type EvalFormData = z.infer<typeof evalFormSchema>;
export type OrgFormData = z.infer<typeof orgFormSchema>;
export type CircuitUploadData = z.infer<typeof circuitUploadSchema>;
export type WebhookFormData = z.infer<typeof webhookFormSchema>;
export type NotificationFormData = z.infer<typeof notificationFormSchema>;
export type SearchFormData = z.infer<typeof searchFormSchema>;
