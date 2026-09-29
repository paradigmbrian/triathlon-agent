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

test("the board tokens are dark first with a daylight variant", () => {
  for (const v of [
    "--surface: #0b0f14;", "--surface-2: #111820;", "--ink: #d9dee5;", "--ink-2: #95a0ae;", "--line: #2e3d52;",
    "--go: #5fd38d;", "--easy: #f2c14e;", "--rest: #ff8f6b;", "--hold: #8fb8ff;",
    "--surface: #f4f5f7;", "--ink: #12161c;", "--ink-2: #555e6b;",
    "--go: #19663a;", "--easy: #7d5400;", "--rest: #a13a18;", "--hold: #2f5fb3;",
  ]) expect(css).toContain(v);
  for (const c of ["go", "easy", "rest", "hold", "good", "warn", "danger"]) expect(css).toContain(`--color-${c}: var(--${c});`);
  expect(css).toContain("prefers-color-scheme: light");
  expect(css).toContain("prefers-reduced-motion: reduce");
  expect(css).toMatch(/button:not\(:disabled\)[^{]*\{\s*cursor: pointer;/);
});

test("the row flash only animates when motion is allowed", () => {
  expect(css).toMatch(/@media \(prefers-reduced-motion: no-preference\)\s*\{[^}]*\.board-flash/);
});
