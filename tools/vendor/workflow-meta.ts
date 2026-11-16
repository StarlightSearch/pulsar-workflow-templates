/**
 * Vendored from StarlightSearch/Pulsar apps/workflows/src/shared/workflow-meta.ts at commit 8029f46b.
 * Byte-for-byte except the import paths below. A test in the Pulsar repo fails when the two differ.
 */
/**
 * What a workflow's SKILL.md says about itself: the frontmatter (name,
 * description, model, output_schema, secrets, inputs), its steps, and its
 * inputs and outputs. Pure and tolerant: a bad SKILL.md yields `errors` the
 * page shows, never a throw, so the overview always renders.
 *
 * Steps come from, in order: the `pulsar-workflow` map (workflow-map.ts);
 * numbered step headings ("### 1. Title", "### Stage 2: Chunk"); a numbered
 * list under a "Steps" / "What to do" style heading. Ids are positional.
 */
import { isMap, isScalar, parseDocument, Scalar } from "yaml";
import type { OverviewStep } from "./workflow-graph-types";
import { clipText, parseHeading, readWorkflowMap, type ResultSlot } from "./workflow-map.ts";

export interface WorkflowInput {
  label: string;
  hint: string;
}

export interface WorkflowOutput {
  label: string;
  hint: string;
}

export interface WorkflowMeta {
  name: string;
  description: string;
  model?: string;
  /** The bare JSON Schema object, or `{ name, schema }` as written. */
  outputSchema?: Record<string, unknown>;
  secrets?: string[];
  /** Apps the workflow needs (lower-case, deduped, at most 20). */
  connections?: string[];
  steps: OverviewStep[];
  stepsFrom: "map" | "headings" | "list" | "none";
  inputs: WorkflowInput[];
  outputs: WorkflowOutput[];
  result: ResultSlot[];
  /** Problems a person should fix, in plain words. Empty when all is well. */
  errors: string[];
}

const FRONTMATTER = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/;
export const CONNECTION_NAME = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const SECRET_NAME = /^[A-Z_][A-Z0-9_]{0,63}$/;

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Splits a SKILL.md into its frontmatter text (null when there is none) and its body. */
export function splitFrontmatter(md: string): { fm: string | null; body: string } {
  const text = md.replace(/\r\n/g, "\n").replace(/^﻿/, "");
  const m = FRONTMATTER.exec(text);
  if (!m) return { fm: null, body: text };
  return { fm: m[1], body: text.slice(m[0].length) };
}

const oneLine = (s: string) => s.replace(/\s+/g, " ").trim();

/** Lines of the section under a heading matching `title` (to the next heading of the same or higher level). */
function section(body: string, title: RegExp): string[] | null {
  const lines = body.split("\n");
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*(```|~~~)/.test(lines[i])) inFence = !inFence;
    if (inFence) continue;
    const h = parseHeading(lines[i], 1, 6);
    if (!h || !title.test(h.title)) continue;
    const level = h.level;
    const out: string[] = [];
    let fence = false;
    for (let j = i + 1; j < lines.length; j++) {
      if (/^\s*(```|~~~)/.test(lines[j])) fence = !fence;
      const n = !fence && /^(#{1,6})\s/.exec(lines[j]);
      if (n && n[1].length <= level) break;
      out.push(lines[j]);
    }
    return out;
  }
  return null;
}

/** "**Label**: hint", "Label: hint" or "Label - hint" as a label and a hint. */
function labelled(text: string): { label: string; hint: string } {
  const t = oneLine(text);
  const bold = /^\*\*(.+?)\*\*\s*[:.\-–]?\s*(.*)$/.exec(t);
  if (bold) return { label: clipText(stripMd(bold[1]), 60), hint: capital(clipText(stripMd(bold[2]), 160)) };
  const colon = /^([^:]{1,60}):\s+(.+)$/.exec(t);
  if (colon) return { label: clipText(stripMd(colon[1]), 60), hint: capital(clipText(stripMd(colon[2]), 160)) };
  return { label: clipText(stripMd(t), 60), hint: "" };
}

const stripMd = (s: string) => unlink(s.replace(/\*\*|__|`/g, "")).trim();

/**
 * `s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")` in linear time: the regex
 * rescans to the next "]" from every "[", quadratic on a long run of them.
 */
export function unlink(s: string): string {
  let out = "";
  let i = 0;
  let closeFrom = -1; // the "]" search result is the same for every "[" before it
  let close = -1;
  let parenFrom = -1;
  let paren = -1;
  while (i < s.length) {
    const open = s.indexOf("[", i);
    if (open < 0) break;
    if (open >= closeFrom) {
      close = s.indexOf("]", open + 1);
      closeFrom = close < 0 ? Infinity : close;
    }
    if (close < 0) break;
    if (close > open + 1 && s[close + 1] === "(") {
      if (close + 2 > parenFrom) {
        paren = s.indexOf(")", close + 2);
        parenFrom = paren < 0 ? Infinity : paren;
      }
      if (paren < 0) break;
      out += s.slice(i, open) + s.slice(open + 1, close);
      i = paren + 1;
      continue;
    }
    out += s.slice(i, open + 1);
    i = open + 1;
  }
  return out + s.slice(i);
}
const capital = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Top-level bullets of a section, each with its continuation lines. */
function bullets(lines: string[]): string[] {
  const out: string[] = [];
  for (const line of lines) {
    const m = /^[-*+]\s+(.*)$/.exec(line);
    if (m) out.push(m[1]);
    else if (out.length && /^\s{2,}\S/.test(line) && !/^\s*[-*+]\s/.test(line)) out[out.length - 1] += " " + line.trim();
  }
  return out;
}

const STEP_HEADING = /^(?:(?:step|stage|phase)\s+)?(\d+)(?:\.(\d+))?\s*[.:)\-–]?\s+(.+)$/i;

/** "### 1. Title" headings (with "#### 1.1 Title" children), in the first section that has two or more. */
function stepsFromHeadings(body: string): OverviewStep[] {
  const lines = body.split("\n");
  let inFence = false;
  const found: { level: number; title: string; detail: string }[] = [];
  let cur: { level: number; title: string; detail: string } | null = null;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const h = !inFence && parseHeading(line, 2, 6);
    if (h) {
      const m = STEP_HEADING.exec(h.title);
      cur = m ? { level: h.level, title: stripMd(m[3]), detail: "" } : null;
      if (cur) found.push(cur);
      continue;
    }
    if (cur && !inFence && !cur.detail && line.trim() && !/^\s*[-*+|>]/.test(line)) cur.detail = stripMd(oneLine(line));
  }
  if (found.length < 2) return [];
  const top = Math.min(...found.map((f) => f.level));
  // Only the top level: without a map nothing says whether sub-steps repeat, so they stay in the prose.
  const roots = found
    .filter((f) => f.level === top)
    .slice(0, 8)
    .map((f, i): OverviewStep => ({ id: `s${i + 1}`, title: clipText(f.title, 40), detail: clipText(f.detail, 160), kind: "action" }));
  return roots.length >= 2 ? roots : [];
}

const STEPS_SECTION = /^(steps|what to do|workflow|procedure|process|pipeline|how to run|instructions)\b/i;

/** "1. **Title** - detail" items under a Steps-style heading. */
function stepsFromList(body: string): OverviewStep[] {
  const lines = section(body, STEPS_SECTION);
  if (!lines) return [];
  const items: string[] = [];
  let fence = false;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    if (fence) continue;
    const m = /^\d+[.)]\s+(.*)$/.exec(line);
    if (m) items.push(m[1]);
    else if (items.length && /^\s{2,}\S/.test(line) && !/^\s*(\d+[.)]|[-*+])\s/.test(line)) items[items.length - 1] += " " + line.trim();
  }
  if (items.length < 2) return [];
  return items.slice(0, 8).map((text, i) => {
    const t = oneLine(text);
    const bold = /^\*\*(.+?)\*\*\s*[:.\-–]?\s*(.*)$/.exec(t);
    const title = bold ? stripMd(bold[1]) : stripMd(t.split(/(?<=[.:])\s/)[0].replace(/[.:]$/, ""));
    const detail = bold ? stripMd(bold[2]) : stripMd(t.slice(t.split(/(?<=[.:])\s/)[0].length));
    return { id: `s${i + 1}`, title: clipText(title, 40), detail: clipText(detail, 160), kind: "action" as const };
  });
}

function inputsFrom(fm: Record<string, unknown>, body: string): WorkflowInput[] {
  const out: WorkflowInput[] = [];
  if (Array.isArray(fm.inputs)) {
    for (const i of fm.inputs.slice(0, 12)) {
      if (typeof i === "string" && i.trim()) out.push(labelled(i));
      else if (isObj(i)) {
        const label = typeof i.label === "string" ? i.label : typeof i.name === "string" ? i.name : "";
        const hint = typeof i.hint === "string" ? i.hint : typeof i.description === "string" ? i.description : "";
        if (label.trim()) out.push({ label: clipText(oneLine(label), 60), hint: clipText(oneLine(hint), 160) });
      }
    }
    if (out.length) return out;
  }
  const lines = section(body, /^inputs?\b/i);
  return lines ? bullets(lines).slice(0, 12).map(labelled) : [];
}

function outputsFrom(schema: Record<string, unknown> | undefined, result: ResultSlot[], body: string): WorkflowOutput[] {
  const inner = schema && isObj(schema.schema) ? schema.schema : schema;
  if (inner && isObj(inner.properties)) {
    return Object.entries(inner.properties)
      .slice(0, 12)
      .map(([key, v]) => ({
        label: key,
        hint: isObj(v) ? clipText(oneLine(typeof v.description === "string" ? v.description : typeof v.type === "string" ? v.type : ""), 160) : "",
      }));
  }
  if (result.length) {
    return result.map((r) => ({ label: r.about || r.type, hint: r.labels?.join(", ") ?? "" }));
  }
  const lines = section(body, /^(outputs?|result|deliverables?)\b/i);
  return lines ? bullets(lines).slice(0, 12).map(labelled) : [];
}

/** The first `# Title` line of the body, or null. */
export function firstHeading(md: string): string | null {
  const { body } = splitFrontmatter(md);
  for (const line of body.split("\n")) {
    const h = parseHeading(line, 1, 1);
    if (h) return clipText(stripMd(h.title), 100);
  }
  return null;
}

/** Everything the page shows about a workflow, from its SKILL.md. Never throws. */
export function parseWorkflowMeta(skillMd: string): WorkflowMeta {
  const errors: string[] = [];
  const { fm: fmText, body } = splitFrontmatter(typeof skillMd === "string" ? skillMd : "");
  let fm: Record<string, unknown> = {};
  if (fmText === null) errors.push("SKILL.md has no frontmatter. It starts with --- and holds name and description.");
  else {
    try {
      const doc = parseDocument(fmText, { prettyErrors: false, uniqueKeys: false });
      if (doc.errors.length) errors.push(`The frontmatter is not valid YAML: ${oneLine(doc.errors[0].message).slice(0, 160)}`);
      else {
        const js: unknown = doc.toJS({ maxAliasCount: 50 });
        if (isObj(js)) fm = js;
        else if (js != null) errors.push("The frontmatter must be a list of key: value lines.");
      }
    } catch (e) {
      errors.push(`The frontmatter is not valid YAML: ${oneLine(e instanceof Error ? e.message : String(e)).slice(0, 160)}`);
    }
  }

  const name = typeof fm.name === "string" ? oneLine(fm.name) : "";
  const description = typeof fm.description === "string" ? oneLine(fm.description) : "";
  if (fmText !== null && !errors.length) {
    if (!name) errors.push("The frontmatter has no name.");
    if (!description) errors.push("The frontmatter has no description.");
  }

  const meta: WorkflowMeta = { name, description, steps: [], stepsFrom: "none", inputs: [], outputs: [], result: [], errors };
  if (fm.model !== undefined) {
    if (typeof fm.model === "string" && fm.model.trim()) meta.model = fm.model.trim();
    else errors.push("model must be a model id.");
  }
  if (fm.output_schema !== undefined) {
    if (isObj(fm.output_schema)) meta.outputSchema = fm.output_schema;
    else errors.push("output_schema must be a JSON Schema object.");
  }
  if (fm.secrets !== undefined) {
    const list = Array.isArray(fm.secrets) ? fm.secrets : typeof fm.secrets === "string" ? fm.secrets.split(",") : null;
    if (!list) errors.push("secrets must be a list of secret names.");
    else {
      const names = list.map((s) => (typeof s === "string" ? s.trim() : s)).filter((s) => s !== "");
      const bad = names.find((s) => typeof s !== "string" || !SECRET_NAME.test(s));
      if (bad !== undefined) errors.push(`secrets: "${clipText(String(bad), 40)}" is not a secret name (capital letters, digits and _).`);
      meta.secrets = [...new Set(names.filter((s): s is string => typeof s === "string" && SECRET_NAME.test(s)))].slice(0, 50);
    }
  }
  if (fm.connections !== undefined) {
    const list = Array.isArray(fm.connections) ? fm.connections : typeof fm.connections === "string" ? fm.connections.split(",") : null;
    if (!list) errors.push("connections must be a list of app names.");
    else {
      const names = list.map((s) => (typeof s === "string" ? s.trim().toLowerCase() : s)).filter((s) => s !== "");
      const bad = names.find((s) => typeof s !== "string" || !CONNECTION_NAME.test(s));
      if (bad !== undefined) errors.push(`connections: "${clipText(String(bad), 40)}" is not an app name.`);
      meta.connections = [...new Set(names.filter((s): s is string => typeof s === "string" && CONNECTION_NAME.test(s)))].slice(0, 20);
    }
  }

  const map = readWorkflowMap(body);
  if (map.status === "valid") {
    meta.steps = map.map.steps;
    meta.stepsFrom = "map";
    meta.result = map.map.result;
  } else {
    if (map.status === "invalid") errors.push(`Workflow map ignored: ${map.errors.slice(0, 3).join("; ")}.`);
    const headed = stepsFromHeadings(body);
    const listed = headed.length ? [] : stepsFromList(body);
    if (headed.length) {
      meta.steps = headed;
      meta.stepsFrom = "headings";
    } else if (listed.length) {
      meta.steps = listed;
      meta.stepsFrom = "list";
    }
  }
  meta.inputs = inputsFrom(fm, body);
  meta.outputs = outputsFrom(meta.outputSchema, meta.result, body);
  return meta;
}

/**
 * The SKILL.md with `name` and/or `description` set in its frontmatter, the
 * rest of the file untouched (comments and key order kept). A description
 * is written as a folded block (`>-`), which no colon or quote can break.
 * Adds a frontmatter block when there is none. Null when the frontmatter is
 * not valid YAML (the caller leaves the file alone).
 */
export function setFrontmatterFields(md: string, fields: { name?: string; description?: string }): string | null {
  const { fm, body } = splitFrontmatter(md);
  const doc = parseDocument(fm ?? "", { prettyErrors: false });
  if (doc.errors.length) return null;
  if (doc.contents !== null && !isMap(doc.contents)) return null;
  if (fields.name !== undefined) doc.set("name", fields.name);
  if (fields.description !== undefined) {
    const s = new Scalar(fields.description);
    s.type = Scalar.BLOCK_FOLDED;
    const existing = doc.get("description", true);
    if (isScalar(existing) && existing.comment) s.comment = existing.comment;
    doc.set("description", s);
  }
  const text = doc.toString({ lineWidth: 100 }).replace(/\n+$/, "");
  return `---\n${text}\n---\n${fm === null && body && !body.startsWith("\n") ? "\n" : ""}${body}`;
}
