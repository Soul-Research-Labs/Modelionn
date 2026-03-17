"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui/toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
  useWebhooks,
  useCreateWebhook,
  useUpdateWebhook,
  useDeleteWebhook,
} from "@/lib/api";
import type { ApiKey, Webhook } from "@/lib/api/client";
import { webhookFormSchema, apiKeyFormSchema } from "@/lib/validation";
import { Key, Plus, Trash2, Copy, Shield, Bell, Power } from "lucide-react";
import { timeAgo } from "@/lib/utils";

const WEBHOOK_EVENTS = [
  { value: "*", label: "All events" },
  { value: "proof.completed", label: "Proof completed" },
  { value: "proof.failed", label: "Proof failed" },
  { value: "circuit.uploaded", label: "Circuit uploaded" },
  { value: "prover.online", label: "Prover online" },
  { value: "prover.offline", label: "Prover offline" },
];

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const { toast } = useToast();
  const { data: apiKeys, isLoading } = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();

  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [newKeyLimit, setNewKeyLimit] = useState(1000);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [apiKeyErrors, setApiKeyErrors] = useState<{ [key: string]: string }>({});

  // Webhook state
  const { data: webhooks, isLoading: webhooksLoading } = useWebhooks();
  const createWebhook = useCreateWebhook();
  const updateWebhook = useUpdateWebhook();
  const deleteWebhook = useDeleteWebhook();
  const [showWebhookForm, setShowWebhookForm] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookLabel, setWebhookLabel] = useState("");
  const [webhookEvents, setWebhookEvents] = useState<string[]>(["*"]);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [webhookErrors, setWebhookErrors] = useState<{ [key: string]: string }>({});

  if (status === "loading") return null;
  if (status === "unauthenticated") {
    router.push("/auth/signin");
    return null;
  }

  const handleCreate = async () => {
    // Validate
    const validation = apiKeyFormSchema.safeParse({
      name: newKeyLabel,
      daily_limit: newKeyLimit,
    });

    if (!validation.success) {
      const errors: { [key: string]: string } = {};
      validation.error.issues.forEach((issue) => {
        const path = issue.path.join(".");
        errors[path] = issue.message;
      });
      setApiKeyErrors(errors);
      return;
    }

    setApiKeyErrors({});
    const result = await createKey.mutateAsync({
      name: newKeyLabel,
      daily_limit: newKeyLimit,
    });
    setCreatedKey(result.key ?? null);
    setShowForm(false);
    setNewKeyLabel("");
    setNewKeyLimit(1000);
    toast("API key created successfully", "success");
  };

  const handleRevoke = async (id: number) => {
    if (!confirm("Revoke this API key? This cannot be undone.")) return;
    await revokeKey.mutateAsync(id);
  };

  const copyKey = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const handleCreateWebhook = async () => {
    // Validate
    const validation = webhookFormSchema.safeParse({
      url: webhookUrl,
      label: webhookLabel,
      events: webhookEvents,
    });

    if (!validation.success) {
      const errors: { [key: string]: string } = {};
      validation.error.issues.forEach((issue) => {
        const path = issue.path.join(".");
        errors[path] = issue.message;
      });
      setWebhookErrors(errors);
      return;
    }

    setWebhookErrors({});
    const result = await createWebhook.mutateAsync({
      url: webhookUrl,
      label: webhookLabel,
      events: webhookEvents,
    });
    setCreatedSecret(result.secret);
    setShowWebhookForm(false);
    setWebhookUrl("");
    setWebhookLabel("");
    setWebhookEvents(["*"]);
    toast("Webhook created successfully", "success");
  };

  const handleDeleteWebhook = async (id: number) => {
    if (!confirm("Delete this webhook? This cannot be undone.")) return;
    await deleteWebhook.mutateAsync(id);
  };

  const toggleWebhook = async (id: number, active: boolean) => {
    await updateWebhook.mutateAsync({ id, active: !active });
  };

  const toggleEvent = (event: string) => {
    if (event === "*") {
      setWebhookEvents(["*"]);
      return;
    }
    const filtered = webhookEvents.filter((e) => e !== "*");
    if (filtered.includes(event)) {
      const next = filtered.filter((e) => e !== event);
      setWebhookEvents(next.length === 0 ? ["*"] : next);
    } else {
      setWebhookEvents([...filtered, event]);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" /> Profile
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-500 w-20">Hotkey:</span>
            <code className="bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-xs">
              {session?.user?.name ?? "—"}
            </code>
          </div>
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" /> API Keys
            </CardTitle>
            <Button
              size="sm"
              onClick={() => setShowForm(!showForm)}
              variant={showForm ? "outline" : "default"}
            >
              <Plus className="h-4 w-4 mr-1" />
              {showForm ? "Cancel" : "Create Key"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* New key banner */}
          {createdKey && (
            <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-900/20 p-4">
              <p className="text-sm font-medium text-green-700 dark:text-green-400 mb-1">
                API key created — copy it now, it will not be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code className="bg-white dark:bg-gray-900 border px-3 py-1 rounded text-xs flex-1 overflow-auto">
                  {createdKey}
                </code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => copyKey(createdKey)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="mt-2 text-xs"
                onClick={() => setCreatedKey(null)}
              >
                Dismiss
              </Button>
            </div>
          )}

          {/* Create form */}
          {showForm && (
            <div className="rounded-lg border p-4 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">Label</label>
                <input
                  type="text"
                  value={newKeyLabel}
                  onChange={(e) => setNewKeyLabel(e.target.value)}
                  placeholder="e.g. CI pipeline"
                  className="w-full rounded-md border px-3 py-1.5 text-sm"
                  maxLength={256}
                />
                              {apiKeyErrors.name && (
                                <p className="text-xs text-red-500 mt-1">{apiKeyErrors.name}</p>
                              )}
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">
                  Daily Limit
                </label>
                <input
                  type="number"
                  value={newKeyLimit}
                  onChange={(e) =>
                    setNewKeyLimit(
                      Math.max(1, Math.min(1000000, Number(e.target.value))),
                    )
                  }
                  min={1}
                  max={1000000}
                  className="w-32 rounded-md border px-3 py-1.5 text-sm"
                />
                {apiKeyErrors.daily_limit && (
                  <p className="text-xs text-red-500 mt-1">{apiKeyErrors.daily_limit}</p>
                )}
              </div>
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={createKey.isPending}
              >
                {createKey.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          )}

          {/* List */}
          {isLoading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : !apiKeys?.length ? (
            <p className="text-sm text-gray-400">
              No API keys yet. Create one to get started.
            </p>
          ) : (
            <div className="divide-y rounded-lg border">
              {apiKeys.map((k: ApiKey) => (
                <div
                  key={k.id}
                  className="flex items-center justify-between px-4 py-3"
                >
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">
                        {k.name || "Unnamed key"}
                      </span>
                      <Badge variant="secondary" className="text-xs">
                        {k.requests_today} / {k.daily_limit}
                      </Badge>
                    </div>
                    <p className="text-xs text-gray-500">
                      Created {timeAgo(k.created_at)} · Prefix {k.key_prefix}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-500 hover:text-red-700"
                    onClick={() => handleRevoke(k.id)}
                    disabled={revokeKey.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Webhooks */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" /> Webhooks
            </CardTitle>
            <Button
              size="sm"
              onClick={() => setShowWebhookForm(!showWebhookForm)}
              variant={showWebhookForm ? "outline" : "default"}
            >
              <Plus className="h-4 w-4 mr-1" />
              {showWebhookForm ? "Cancel" : "Add Webhook"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Secret banner */}
          {createdSecret && (
            <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-900/20 p-4">
              <p className="text-sm font-medium text-green-700 dark:text-green-400 mb-1">
                Webhook secret — copy it now, it will not be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code className="bg-white dark:bg-gray-900 border px-3 py-1 rounded text-xs flex-1 overflow-auto">
                  {createdSecret}
                </code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => copyKey(createdSecret)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Use this secret to verify webhook signatures (HMAC-SHA256 of the
                payload).
              </p>
              <Button
                size="sm"
                variant="ghost"
                className="mt-2 text-xs"
                onClick={() => setCreatedSecret(null)}
              >
                Dismiss
              </Button>
            </div>
          )}

          {/* Create form */}
          {showWebhookForm && (
            <div className="rounded-lg border p-4 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">
                  URL (HTTPS)
                </label>
                <input
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://example.com/webhook"
                  className="w-full rounded-md border px-3 py-1.5 text-sm"
                  maxLength={2048}
                />
                {webhookErrors.url && (
                  <p className="text-xs text-red-500 mt-1">{webhookErrors.url}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Label</label>
                <input
                  type="text"
                  value={webhookLabel}
                  onChange={(e) => setWebhookLabel(e.target.value)}
                  placeholder="e.g. Slack notifications"
                  className="w-full rounded-md border px-3 py-1.5 text-sm"
                  maxLength={256}
                />
                {webhookErrors.label && (
                  <p className="text-xs text-red-500 mt-1">{webhookErrors.label}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Events</label>
                <div className="flex flex-wrap gap-2">
                  {WEBHOOK_EVENTS.map((evt) => (
                    <button
                      key={evt.value}
                      type="button"
                      onClick={() => toggleEvent(evt.value)}
                      className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                        webhookEvents.includes(evt.value)
                          ? "bg-blue-100 border-blue-300 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                          : "bg-gray-50 border-gray-200 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                      }`}
                    >
                      {evt.label}
                    </button>
                  ))}
                </div>
                {webhookErrors.events && (
                  <p className="text-xs text-red-500 mt-1">{webhookErrors.events}</p>
                )}
              </div>
              <Button
                size="sm"
                onClick={handleCreateWebhook}
                disabled={createWebhook.isPending}
              >
                {createWebhook.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          )}

          {/* Webhook list */}
          {webhooksLoading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : !webhooks?.length ? (
            <p className="text-sm text-gray-400">
              No webhooks configured. Add one to receive event notifications.
            </p>
          ) : (
            <div className="divide-y rounded-lg border">
              {webhooks.map((wh: Webhook) => (
                <div
                  key={wh.id}
                  className="flex items-center justify-between px-4 py-3"
                >
                  <div className="space-y-0.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">
                        {wh.label || wh.url}
                      </span>
                      <Badge
                        variant={wh.active ? "default" : "secondary"}
                        className="text-xs"
                      >
                        {wh.active ? "Active" : "Paused"}
                      </Badge>
                    </div>
                    <p className="text-xs text-gray-500 truncate">{wh.url}</p>
                    <div className="flex gap-1 mt-1">
                      {wh.events.map((evt) => (
                        <Badge key={evt} variant="outline" className="text-xs">
                          {evt}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 ml-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => toggleWebhook(wh.id, wh.active)}
                      title={wh.active ? "Pause" : "Activate"}
                    >
                      <Power className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-500 hover:text-red-700"
                      onClick={() => handleDeleteWebhook(wh.id)}
                      disabled={deleteWebhook.isPending}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
