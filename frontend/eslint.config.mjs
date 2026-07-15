import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

export default [
  ...nextCoreWebVitals,
  {
    rules: {
      // React Compiler rules — not using React Compiler
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/preserve-manual-memoization": "off",
    },
  },
  {
    // Ban bare fetch() in the API client: every request must go through the
    // ApiClient.fetch() wrapper, which adds the Bearer auth header and handles
    // 401 -> refresh -> retry. The handful of unavoidable low-level call sites
    // (the wrapper's own primitive, fire-and-forget logout, raw/streaming/
    // non-enveloped responses) each carry an explicit eslint-disable-next-line
    // with a reason. Regression guard for the DELETE-bypass fix (audit 2026-07 R9).
    files: ["**/lib/api/client.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            "Bare fetch() bypasses the Bearer-auth + 401-refresh wrapper. Route the call through this.fetch(). If a raw/streaming/non-enveloped response is genuinely required, add an `eslint-disable-next-line no-restricted-syntax` with a reason.",
        },
      ],
    },
  },
];
