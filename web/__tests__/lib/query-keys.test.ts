import {
  makeQueryKey,
  makePaginatedKey,
  makeSingleKey,
} from "@/lib/query-keys";

describe("makeQueryKey", () => {
  it("returns base key only when no params", () => {
    expect(makeQueryKey("circuits")).toEqual(["circuits"]);
  });

  it("normalizes param key order", () => {
    const a = makeQueryKey("jobs", { page: 1, status: "active" });
    const b = makeQueryKey("jobs", { status: "active", page: 1 });
    expect(a).toEqual(b);
  });

  it("includes params in tuple", () => {
    const key = makeQueryKey("provers", { online: true });
    expect(key).toEqual(["provers", { online: true }]);
  });
});

describe("makePaginatedKey", () => {
  it("delegates to makeQueryKey", () => {
    const key = makePaginatedKey("jobs", { page: 2, page_size: 20 });
    expect(key).toEqual(["jobs", { page: 2, page_size: 20 }]);
  });
});

describe("makeSingleKey", () => {
  it("returns base key with id", () => {
    expect(makeSingleKey("circuit", 42)).toEqual(["circuit", 42]);
  });

  it("works with string ids", () => {
    expect(makeSingleKey("proof", "abc")).toEqual(["proof", "abc"]);
  });
});
