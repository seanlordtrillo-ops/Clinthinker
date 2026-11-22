import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

globalThis.window = { location: { origin: "http://localhost" } };
const { api, formatApiError } = await import("./api.js");

assert.equal(formatApiError("Invalid request", "Fallback"), "Invalid request");
assert.equal(
  formatApiError(
    [
      { loc: ["body", "count"], msg: "Value error, Must be positive", type: "value_error" },
      { loc: ["body", "name"], msg: "Field required", type: "missing" }
    ],
    "Fallback"
  ),
  "Must be positive; Field required"
);
assert.equal(formatApiError(undefined, "Fallback"), "Fallback");

const originalFetch = globalThis.fetch;
const fetchCalls = [];
globalThis.fetch = async (...args) => {
  fetchCalls.push(args);
  return {
    ok: true,
    json: async () => ({ started: true })
  };
};
try {
  assert.deepEqual(await api.installUpdate(), { started: true });
} finally {
  globalThis.fetch = originalFetch;
}
assert.deepEqual(fetchCalls, [[
  "http://localhost/api/updates/install",
  {
    method: "POST",
    headers: { "X-Clinthinker-Request": "1" }
  }
]]);

const serverUpdateError = "Update failed at the download step: the download timed out. Check your connection and try again.";
globalThis.fetch = async () => ({
  ok: false,
  status: 500,
  json: async () => ({ detail: serverUpdateError })
});
try {
  await assert.rejects(api.installUpdate(), (error) => {
    assert.equal(error.message, serverUpdateError);
    assert.equal(error.status, 500);
    return true;
  });
} finally {
  globalThis.fetch = originalFetch;
}

const appSource = await readFile(new URL("../App.jsx", import.meta.url), "utf8");
assert.ok(appSource.includes("Installing update. The app will close and restart."));
assert.ok(appSource.includes("If the app did not close, close it to finish installing."));
assert.match(appSource, /updateState === "installing"\s*\?\s*updateInstallMessage/);
assert.doesNotMatch(appSource, /window\.close\(\)/);

console.log("API error formatting tests passed.");
