import {
  evalFormSchema,
  orgFormSchema,
  circuitUploadSchema,
  webhookFormSchema,
  apiKeyFormSchema,
  searchFormSchema,
} from "@/lib/validation";

describe("evalFormSchema", () => {
  const valid = {
    artifact_name: "my-circuit",
    artifact_version: "1.0.0",
    submitter_hotkey: "5" + "A".repeat(47),
  };

  it("accepts valid input", () => {
    expect(evalFormSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects invalid hotkey", () => {
    expect(
      evalFormSchema.safeParse({ ...valid, submitter_hotkey: "nope" }).success,
    ).toBe(false);
  });
});

describe("orgFormSchema", () => {
  it("accepts valid org", () => {
    const result = orgFormSchema.safeParse({ name: "Acme", slug: "acme-123" });
    expect(result.success).toBe(true);
  });

  it("rejects uppercase slug", () => {
    expect(
      orgFormSchema.safeParse({ name: "X", slug: "Bad-Slug" }).success,
    ).toBe(false);
  });
});

describe("circuitUploadSchema", () => {
  const valid = {
    name: "test-circuit",
    version: "1.0",
    proof_type: "groth16" as const,
    circuit_type: "general" as const,
    num_constraints: 1000,
    data_cid: "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
    publisher_hotkey: "5" + "B".repeat(47),
  };

  it("accepts valid circuit upload", () => {
    expect(circuitUploadSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects missing CID", () => {
    const { data_cid, ...rest } = valid;
    expect(circuitUploadSchema.safeParse(rest).success).toBe(false);
  });

  it("rejects invalid proof type", () => {
    expect(
      circuitUploadSchema.safeParse({ ...valid, proof_type: "foo" }).success,
    ).toBe(false);
  });

  it("rejects non-positive constraints", () => {
    expect(
      circuitUploadSchema.safeParse({ ...valid, num_constraints: 0 }).success,
    ).toBe(false);
  });
});

describe("webhookFormSchema", () => {
  const valid = {
    url: "https://example.com/hook",
    label: "My Webhook",
    events: ["proof.completed"],
  };

  it("accepts valid webhook", () => {
    expect(webhookFormSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects non-HTTPS URL", () => {
    expect(
      webhookFormSchema.safeParse({ ...valid, url: "http://example.com" })
        .success,
    ).toBe(false);
  });

  it("rejects empty events", () => {
    expect(
      webhookFormSchema.safeParse({ ...valid, events: [] }).success,
    ).toBe(false);
  });

  it("rejects invalid event type", () => {
    expect(
      webhookFormSchema.safeParse({ ...valid, events: ["invalid.event"] })
        .success,
    ).toBe(false);
  });

  it("accepts wildcard event", () => {
    expect(
      webhookFormSchema.safeParse({ ...valid, events: ["*"] }).success,
    ).toBe(true);
  });
});

describe("apiKeyFormSchema", () => {
  it("accepts valid key config", () => {
    expect(
      apiKeyFormSchema.safeParse({ name: "Test Key", daily_limit: 1000 })
        .success,
    ).toBe(true);
  });

  it("rejects negative daily limit", () => {
    expect(
      apiKeyFormSchema.safeParse({ name: "Key", daily_limit: -1 }).success,
    ).toBe(false);
  });
});

describe("searchFormSchema", () => {
  it("accepts short query", () => {
    expect(searchFormSchema.safeParse({ query: "hello" }).success).toBe(true);
  });

  it("rejects overly long query", () => {
    expect(
      searchFormSchema.safeParse({ query: "x".repeat(300) }).success,
    ).toBe(false);
  });
});
