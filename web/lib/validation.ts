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

export const webhookFormSchema = z.object({
  url: z
    .string()
    .url("Must be a valid URL")
    .startsWith("https://", "Webhook URL must use HTTPS"),
  events: z.string().max(500, "Too many events"),
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
export type WebhookFormData = z.infer<typeof webhookFormSchema>;
export type NotificationFormData = z.infer<typeof notificationFormSchema>;
export type SearchFormData = z.infer<typeof searchFormSchema>;
