"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useMyOrgs, useCreateOrg } from "@/lib/api";
import { orgFormSchema } from "@/lib/validation";
import { Building2, Plus, ArrowRight } from "lucide-react";

export default function OrganizationsPage() {
  const { status } = useSession();
  const router = useRouter();
  const { data: orgs, isLoading } = useMyOrgs();
  const createOrg = useCreateOrg();

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [formErrors, setFormErrors] = useState<{ [key: string]: string }>({});

  if (status === "unauthenticated") {
    router.push("/auth/signin");
    return null;
  }

  const handleCreate = () => {
    const payload = { name: name.trim(), slug: slug.trim() };
    const validation = orgFormSchema.safeParse(payload);
    if (!validation.success) {
      const errors: { [key: string]: string } = {};
      validation.error.issues.forEach((issue) => {
        const path = issue.path.join(".");
        errors[path] = issue.message;
      });
      setFormErrors(errors);
      return;
    }

    setFormErrors({});
    createOrg.mutate(
      payload,
      {
        onSuccess: () => {
          setShowForm(false);
          setName("");
          setSlug("");
          setFormErrors({});
        },
      },
    );
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organizations</h1>
          <p className="mt-1 text-gray-500">
            Manage your organizations and team members.
          </p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)}>
          <Plus className="mr-2 h-4 w-4" />
          New Organization
        </Button>
      </div>

      {/* Create form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>Create Organization</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label
                htmlFor="org-name"
                className="block text-sm font-medium text-gray-700"
              >
                Name
              </label>
              <input
                id="org-name"
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  // Auto-generate slug from name
                  setSlug(
                    e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-|-$/g, ""),
                  );
                }}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
                placeholder="My Organization"
              />
              {formErrors.name && (
                <p className="mt-1 text-xs text-red-600">{formErrors.name}</p>
              )}
            </div>
            <div>
              <label
                htmlFor="org-slug"
                className="block text-sm font-medium text-gray-700"
              >
                Slug
              </label>
              <input
                id="org-slug"
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
                placeholder="my-organization"
              />
              {formErrors.slug && (
                <p className="mt-1 text-xs text-red-600">{formErrors.slug}</p>
              )}
              <p className="mt-1 text-xs text-gray-400">
                Lowercase letters, numbers, and hyphens only.
              </p>
            </div>
            <div className="flex gap-2">
              <Button onClick={handleCreate} disabled={createOrg.isPending}>
                {createOrg.isPending ? "Creating..." : "Create"}
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
            {createOrg.isError && (
              <p className="text-sm text-red-600">
                {createOrg.error?.message || "Failed to create organization."}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Org list */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-lg bg-gray-100"
            />
          ))}
        </div>
      ) : orgs && orgs.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {orgs.map((org) => (
            <Link key={org.id} href={`/organizations/${org.slug}`}>
              <Card className="cursor-pointer transition-shadow hover:shadow-md">
                <CardContent className="flex items-center gap-4 p-5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50">
                    <Building2 className="h-5 w-5 text-brand-600" />
                  </div>
                  <div className="flex-1">
                    <p className="font-semibold">{org.name}</p>
                    <p className="text-sm text-gray-400">/{org.slug}</p>
                  </div>
                  <ArrowRight className="h-4 w-4 text-gray-400" />
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-12 text-center">
            <Building2 className="mx-auto h-12 w-12 text-gray-300" />
            <p className="mt-4 text-gray-500">
              You don&apos;t belong to any organizations yet.
            </p>
            <Button className="mt-4" onClick={() => setShowForm(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create your first organization
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
