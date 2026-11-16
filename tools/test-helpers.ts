import { cpSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

export const REPO = resolve(import.meta.dirname, "..");

/** A temp repo root holding categories.json and a copy of tools/fixtures/hello-template under `slug`. Returns [root, templateDir]. */
export function fixture(slug = "hello-template"): [string, string] {
  const root = mkdtempSync(join(tmpdir(), "tpl-"));
  cpSync(join(REPO, "categories.json"), join(root, "categories.json"));
  const dir = join(root, "templates", slug);
  cpSync(join(REPO, "tools", "fixtures", "hello-template"), dir, { recursive: true });
  return [root, dir];
}
