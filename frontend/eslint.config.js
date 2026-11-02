// Lint for the frontend (spec 007 section 12.8): recommended JavaScript and TypeScript
// rules plus the rules of hooks.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": ["error", {
        selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
        message: "Raw HTML injection is not allowed (spec 007 section 11).",
      }],
    },
  },
);
