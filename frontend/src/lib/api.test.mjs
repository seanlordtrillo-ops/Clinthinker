import assert from "node:assert/strict";

globalThis.window = { location: { origin: "http://localhost" } };
const { formatApiError } = await import("./api.js");

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

console.log("API error formatting tests passed.");
