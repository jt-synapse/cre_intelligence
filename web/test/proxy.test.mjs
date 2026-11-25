import test from "node:test";
import assert from "node:assert/strict";
import { upstreamURL, isLoopback, copyRequestHeaders } from "../lib/proxy.mjs";

test("parcel filters reach the configured upstream and keep query encoding", () => {
  assert.equal(
    upstreamURL("http://api:8000", ["parcels"], "?q=Main%20St"),
    "http://api:8000/v1/parcels?q=Main%20St",
  );
});
test("paths cannot escape the fixed API prefix", () => {
  for (const part of ["..", "a/b", "%2e%2e", "//other.test", "a?secret=1"]) {
    assert.throws(() => upstreamURL("http://api:8000", [part], ""));
  }
});
test("loopback demo excludes domains that merely contain localhost", () => {
  for (const value of ["localhost", "127.0.0.1", "[::1]"])
    assert.equal(isLoopback(value), true);
  assert.equal(isLoopback("localhost.example.com"), false);
});
test("only the API authentication and content headers are forwarded", () => {
  const headers = copyRequestHeaders(
    new Headers({
      authorization: "Bearer test",
      "x-organization-id": "org",
      "content-type": "application/json",
      cookie: "ignored",
      host: "invalid",
    }),
  );
  assert.deepEqual([...headers.keys()].sort(), [
    "authorization",
    "content-type",
    "x-organization-id",
  ]);
});
test("source links accept public HTTP(S) URLs and exclude opaque object references", async () => {
  const { publicSourceURL } = await import("../lib/proxy.mjs");
  assert.equal(
    publicSourceURL("https://gis.example.gov/parcel/123"),
    "https://gis.example.gov/parcel/123",
  );
  for (const uri of [
    "s3://private/key",
    "javascript:doSomething()",
    "file:///tmp/example",
    "https://user:password@source.test",
    "/local/path",
  ])
    assert.equal(publicSourceURL(uri), null);
});
