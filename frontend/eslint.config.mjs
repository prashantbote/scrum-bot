import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/mockServiceWorker.js", "playwright-report/**", "test-results/**"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["src/**/*.tsx"],
    rules: {
      // Design-system guard: colors come from tokens.css via Tailwind classes, never hex literals.
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/#[0-9a-fA-F]{3,8}\\b/]",
          message: "Hard-coded colors are not allowed. Use design tokens (Tailwind classes or var(--token)).",
        },
        {
          selector: "TemplateElement[value.raw=/#[0-9a-fA-F]{3,8}\\b/]",
          message: "Hard-coded colors are not allowed. Use design tokens (Tailwind classes or var(--token)).",
        },
      ],
    },
  },
];

export default config;
