import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import Ajv from "ajv";
import { parseWorkflowMeta } from "./vendor/workflow-meta";

export const LIMITS = { files: 40, templateBytes: 2 * 1024 * 1024, fileBytes: 1024 * 1024 };
export const LICENSES = ["Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "CC-BY-4.0"];
const PREFIXES = ["/workspace/workflow/", "/workspace/inputs/", "/workspace/out/", "/workspace/knowledge/"];

const schema = JSON.parse(readFileSync(resolve(import.meta.dirname, "schema/template.schema.json"), "utf8"));
const checkSchema = new Ajv({ allErrors: true }).compile(schema);

interface Entry {
  rel: string;
  size: number;
}

/** Every regular file under `dir` (relative, "/" separated), plus the problems met on the way. */
function walk(dir: string, errors: string[], rel = ""): Entry[] {
  const out: Entry[] = [];
  for (const name of readdirSync(join(dir, rel)).sort()) {
    const r = rel ? `${rel}/${name}` : name;
    if (name.startsWith(".")) {
      errors.push(`${r}: dotfiles are not allowed`);
      continue;
    }
    const st = lstatSync(join(dir, r));
    if (st.isSymbolicLink()) errors.push(`${r}: symlinks are not allowed`);
    else if (st.isDirectory()) out.push(...walk(dir, errors, r));
    else if (st.isFile()) out.push({ rel: r, size: st.size });
  }
  return out;
}

/** Template-relative path problems for a name taken from evals or a step. */
function badRelPath(p: string): string | null {
  if (typeof p !== "string" || !p) return "is not a path";
  if (p.startsWith("/") || /^[A-Za-z]:/.test(p)) return "must be relative";
  const parts = p.split("/");
  if (parts.includes("..")) return "must not contain ..";
  if (parts.some((s) => s.startsWith("."))) return "must not contain a dotfile segment";
  return null;
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && [...a].sort().every((v, i) => v === [...b].sort()[i]);

/** Errors for one template folder; empty means valid. The repo root is two levels up (`<root>/templates/<slug>`). */
export function validateTemplate(dir: string): string[] {
  const errors: string[] = [];
  const slug = basename(dir);
  const root = resolve(dir, "../..");

  const entries = walk(dir, errors);
  const has = new Set(entries.map((e) => e.rel));
  if (entries.length > LIMITS.files) errors.push(`${entries.length} files, at most ${LIMITS.files} are allowed`);
  for (const e of entries) if (e.size > LIMITS.fileBytes) errors.push(`${e.rel}: ${e.size} bytes exceeds 1 MB`);
  const total = entries.reduce((n, e) => n + e.size, 0);
  if (total > LIMITS.templateBytes) errors.push(`template is ${total} bytes, over the 2 MB limit`);

  // template.json
  let tpl: any = null;
  if (!has.has("template.json")) errors.push("template.json is missing");
  else {
    const text = readFileSync(join(dir, "template.json"), "utf8");
    try {
      tpl = JSON.parse(text);
    } catch (e) {
      errors.push(`template.json is not valid JSON: ${(e as Error).message}`);
    }
    if (text.includes("—")) errors.push("template.json contains an em-dash");
  }
  if (tpl) {
    if (!checkSchema(tpl)) for (const e of checkSchema.errors ?? []) errors.push(`template.json${e.instancePath} ${e.message}`);
    if (tpl.slug !== slug) errors.push(`slug "${tpl.slug}" must equal the folder name "${slug}"`);
    try {
      const cats: { id: string }[] = JSON.parse(readFileSync(join(root, "categories.json"), "utf8"));
      if (!cats.some((c) => c.id === tpl.category)) errors.push(`category "${tpl.category}" is not in categories.json`);
    } catch {
      errors.push("categories.json is missing or not valid JSON");
    }
    if (tpl.source && typeof tpl.source.license === "string" && !LICENSES.includes(tpl.source.license))
      errors.push(`licence "${tpl.source.license}" is not allowed (${LICENSES.join(", ")})`);
  }

  // SKILL.md
  if (!has.has("SKILL.md")) errors.push("SKILL.md is missing");
  else {
    const md = readFileSync(join(dir, "SKILL.md"), "utf8");
    const meta = parseWorkflowMeta(md);
    for (const e of meta.errors) errors.push(`SKILL.md: ${e}`);
    if (md.includes("—")) errors.push("SKILL.md contains an em-dash");
    if (tpl?.needs) {
      if (Array.isArray(tpl.needs.secrets) && !sameSet(tpl.needs.secrets, meta.secrets ?? []))
        errors.push(`needs.secrets [${tpl.needs.secrets}] must equal the SKILL.md frontmatter secrets [${meta.secrets ?? []}]`);
      if (Array.isArray(tpl.needs.connections) && !sameSet(tpl.needs.connections, meta.connections ?? []))
        errors.push(`needs.connections [${tpl.needs.connections}] must equal the SKILL.md frontmatter connections [${meta.connections ?? []}]`);
    }
    checkWorkspacePaths(md, has, errors);
  }

  // evals
  if (!has.has("evals/evals.json")) errors.push("evals/evals.json is missing");
  else {
    try {
      const ev = JSON.parse(readFileSync(join(dir, "evals/evals.json"), "utf8"));
      if (!Array.isArray(ev?.evals) || ev.evals.length < 1) errors.push("evals/evals.json needs at least one entry in evals");
      else
        ev.evals.forEach((item: any, i: number) => {
          if (typeof item?.prompt !== "string" || !item.prompt) errors.push(`evals[${i}] has no prompt`);
          if (!Array.isArray(item?.files)) errors.push(`evals[${i}].files must be a list`);
          else
            for (const f of item.files) {
              const bad = badRelPath(f);
              if (bad) errors.push(`evals[${i}].files "${f}" ${bad}`);
              else if (!has.has(f)) errors.push(`evals[${i}].files names ${f}, which is not in the template`);
            }
          if (!Array.isArray(item?.expectations)) errors.push(`evals[${i}].expectations must be a list`);
        });
    } catch (e) {
      errors.push(`evals/evals.json is not valid JSON: ${(e as Error).message}`);
    }
  }
  return errors;
}

/** Workflow paths in SKILL.md: only the four prefixes, /workspace/inputs/ never fenced, workflow files must exist. */
function checkWorkspacePaths(md: string, has: Set<string>, errors: string[]) {
  let fenced = false;
  const seen = new Set<string>();
  for (const line of md.replace(/\r\n/g, "\n").split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced;
      continue;
    }
    for (const m of line.matchAll(/\/workspace(?:\/[A-Za-z0-9_.\-/]*)?/g)) {
      const p = m[0].replace(/[.,;:)]+$/, "");
      const prefix = PREFIXES.find((x) => p.startsWith(x) || p + "/" === x);
      if (!prefix) {
        if (!seen.has(`o:${p}`)) errors.push(`SKILL.md: ${p} is not one of ${PREFIXES.join(", ")}`);
        seen.add(`o:${p}`);
        continue;
      }
      if (prefix === "/workspace/inputs/" && fenced && !seen.has("fence")) {
        seen.add("fence");
        errors.push("SKILL.md: /workspace/inputs/ must not appear inside a fenced code block");
      }
      if (prefix === "/workspace/workflow/" && p.length > prefix.length && !seen.has(`w:${p}`)) {
        seen.add(`w:${p}`);
        const rel = p.slice(prefix.length);
        const ok = rel.endsWith("/") ? [...has].some((f) => f.startsWith(rel)) : has.has(rel);
        if (!ok) errors.push(`SKILL.md: ${p} is not in the template (${rel})`);
      }
    }
  }
}

/** Every templates/* folder under `root`, plus the unique-slug check. */
export function validateAll(root: string): { slug: string; errors: string[] }[] {
  const tdir = join(root, "templates");
  const slugs = existsSync(tdir) ? readdirSync(tdir).filter((n) => lstatSync(join(tdir, n)).isDirectory()).sort() : [];
  return slugs.map((slug) => ({ slug, errors: validateTemplate(join(tdir, slug)) }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = resolve(dirname(process.argv[1]), "..");
  const results = validateAll(root);
  let bad = 0;
  for (const r of results) {
    if (r.errors.length) bad++;
    for (const e of r.errors) console.error(`${r.slug}: ${e}`);
  }
  console.log(`${results.length} template(s) checked, ${bad} with errors`);
  process.exit(bad ? 1 : 0);
}
