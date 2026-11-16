import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { pathToFileURL } from "node:url";
import { parseWorkflowMeta } from "./vendor/workflow-meta";

export interface CatalogTemplate {
  slug: string;
  title: string;
  category: string;
  summary: string;
  takes: string;
  gives: string;
  icon: string;
  source?: { name: string; repo: string; path: string; license: string };
  needs: { web: boolean; connections: string[]; secrets: string[] };
  targets: ("workflows" | "pulsar")[];
  steps: string[];
  files: { path: string; size: number; sha256: string }[];
}
export interface Catalog {
  version: 1;
  commit: string;
  builtAt: string;
  categories: { id: string; title: string; order: number }[];
  templates: CatalogTemplate[];
}

function listFiles(dir: string, rel = ""): string[] {
  const out: string[] = [];
  for (const name of readdirSync(join(dir, rel)).sort()) {
    const r = rel ? `${rel}/${name}` : name;
    if (statSync(join(dir, r)).isDirectory()) out.push(...listFiles(dir, r));
    else out.push(r);
  }
  return out;
}

export function buildCatalog(root: string, commit: string): Catalog {
  const categories: Catalog["categories"] = JSON.parse(readFileSync(join(root, "categories.json"), "utf8"));
  const order = new Map(categories.map((c) => [c.id, c.order]));
  const tdir = join(root, "templates");
  const templates: CatalogTemplate[] = readdirSync(tdir)
    .sort()
    .filter((n) => statSync(join(tdir, n)).isDirectory())
    .map((slug) => {
      const dir = join(tdir, slug);
      const t = JSON.parse(readFileSync(join(dir, "template.json"), "utf8"));
      const meta = parseWorkflowMeta(readFileSync(join(dir, "SKILL.md"), "utf8"));
      const files = listFiles(dir)
        .filter((p) => p !== "template.json")
        .map((path) => {
          const buf = readFileSync(join(dir, path));
          return { path, size: buf.length, sha256: createHash("sha256").update(buf).digest("hex") };
        });
      const out: CatalogTemplate = {
        slug: t.slug, title: t.title, category: t.category, summary: t.summary, takes: t.takes, gives: t.gives, icon: t.icon,
        ...(t.source ? { source: t.source } : {}),
        needs: t.needs, targets: t.targets, steps: meta.steps.map((s) => s.title), files,
      };
      return out;
    });
  templates.sort((a, b) => (order.get(a.category) ?? 1e9) - (order.get(b.category) ?? 1e9) || a.title.localeCompare(b.title));
  return { version: 1, commit, builtAt: new Date().toISOString(), categories, templates };
}

/** Writes catalog.json unless the existing one has the same templates and categories (then builtAt and commit stay). True when written. */
export function writeCatalog(root: string, commit: string): boolean {
  const cat = buildCatalog(root, commit);
  const file = join(root, "catalog.json");
  if (existsSync(file)) {
    try {
      const old = JSON.parse(readFileSync(file, "utf8"));
      if (isDeepStrictEqual(old.templates, cat.templates) && isDeepStrictEqual(old.categories, cat.categories)) return false;
    } catch {
      // unreadable: rewrite it
    }
  }
  writeFileSync(file, JSON.stringify(cat, null, 2) + "\n");
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = resolve(dirname(process.argv[1]), "..");
  const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
  console.log(writeCatalog(root, commit) ? `catalog.json rebuilt at ${commit.slice(0, 8)}` : "catalog.json unchanged");
}
