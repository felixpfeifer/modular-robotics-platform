import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/",
      "node_modules/",
      ".pnp.cjs",
      ".pnp.loader.mjs",
      ".yarn/",
      ".image-context/",
      "test-results/",
      "playwright-report/",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat["recommended-latest"], jsxA11y.flatConfigs.recommended],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      // Every promise is awaited, returned or explicitly discarded with `void`.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: false }],
      "@typescript-eslint/no-non-null-assertion": "warn",
      // `role` is also a prop of our own components (leader/follower), not only an ARIA role.
      "jsx-a11y/aria-role": ["error", { ignoreNonDOM: true }],
      // Focusing the first field of a dialog the user just opened is the expected behaviour.
      "jsx-a11y/no-autofocus": "off",
    },
  },
);
