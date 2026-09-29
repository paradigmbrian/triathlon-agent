// @vitest-environment node
/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const src = fileURLToPath(new URL("../src", import.meta.url));
const files = (dir: string): string[] =>
  readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
const css = readFileSync(join(src, "index.css"), "utf8");

test("no text below 12px anywhere in src", () => {
  const offenders = files(src).filter((f) => /text-\[(?:\d|1[01])px\]/.test(readFileSync(f, "utf8")));
  expect(offenders).toEqual([]);
});

test("pulses only run when motion is allowed", () => {
  const bare = files(src).filter((f) => /(^|[\s"`])animate-pulse/.test(readFileSync(f, "utf8")));
  expect(bare).toEqual([]);
});

test("the tokens pass contrast and include good", () => {
  expect(css).toContain("--warn: #805800;");
  expect(css).toContain("--good: #23703a;");
  expect(css).toContain("--good: #6fcf97;");
  expect(css).toContain("--line: #d6d3c8;");
  expect(css).toContain("--line: #3a3e47;");
  expect(css).toContain("--color-good: var(--good);");
  expect(css).toContain("prefers-reduced-motion: reduce");
  expect(css).toMatch(/button:not\(:disabled\)[^{]*\{\s*cursor: pointer;/);
});
