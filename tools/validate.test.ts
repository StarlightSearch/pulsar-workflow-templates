import { mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixture } from "./test-helpers";
import { caseClashes, validateAll, validateTemplate } from "./validate";

const read = (p: string) => readFileSync(p, "utf8");
function editJson(file: string, fn: (j: any) => void) {
  const j = JSON.parse(read(file));
  fn(j);
  writeFileSync(file, JSON.stringify(j, null, 2));
}
const has = (errs: string[], re: RegExp) => errs.some((e) => re.test(e));

describe("validateTemplate", () => {
  it("accepts the hello-template fixture", () => {
    const [, dir] = fixture();
    expect(validateTemplate(dir)).toEqual([]);
  });

  it("rejects slug != folder", () => {
    const [, dir] = fixture("other-name");
    expect(has(validateTemplate(dir), /slug/)).toBe(true);
  });

  it("rejects unknown category", () => {
    const [, dir] = fixture();
    editJson(join(dir, "template.json"), (j) => (j.category = "nope"));
    expect(has(validateTemplate(dir), /category/)).toBe(true);
  });

  it("rejects SKILL.md parse errors", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), "no frontmatter here\n");
    expect(has(validateTemplate(dir), /SKILL\.md/)).toBe(true);
  });

  it("rejects missing name or description", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), "---\nname: hello-template\n---\n\n## Steps\n");
    expect(has(validateTemplate(dir), /description/)).toBe(true);
  });

  it("rejects evals with no entry or a missing file", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "evals/evals.json"), JSON.stringify({ evals: [] }));
    expect(has(validateTemplate(dir), /evals/)).toBe(true);
    writeFileSync(join(dir, "evals/evals.json"), JSON.stringify({ evals: [{ prompt: "p", files: ["samples/missing.txt"], expectations: [] }] }));
    expect(has(validateTemplate(dir), /samples\/missing\.txt/)).toBe(true);
  });

  it("rejects ../ path, dotfile, symlink", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "evals/evals.json"), JSON.stringify({ evals: [{ prompt: "p", files: ["../x.txt"], expectations: [] }] }));
    expect(has(validateTemplate(dir), /\.\./)).toBe(true);
    const [, d2] = fixture();
    writeFileSync(join(d2, ".hidden"), "x");
    expect(has(validateTemplate(d2), /dotfile|hidden/i)).toBe(true);
    const [, d3] = fixture();
    symlinkSync("SKILL.md", join(d3, "link.md"));
    expect(has(validateTemplate(d3), /symlink/)).toBe(true);
  });

  it("rejects 41 files", () => {
    const [, dir] = fixture(); // 4 files already
    mkdirSync(join(dir, "references"));
    for (let i = 0; i < 37; i++) writeFileSync(join(dir, "references", `f${i}.md`), "x");
    expect(has(validateTemplate(dir), /41 files/)).toBe(true);
  });

  it("rejects 1 MB + 1 file", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "samples/big.bin"), Buffer.alloc(1024 * 1024 + 1));
    expect(has(validateTemplate(dir), /big\.bin/)).toBe(true);
  });

  it("rejects 2 MB + 1 template", () => {
    const [, dir] = fixture();
    for (let i = 0; i < 3; i++) writeFileSync(join(dir, "samples", `b${i}.bin`), Buffer.alloc(900 * 1024));
    const errs = validateTemplate(dir);
    expect(has(errs, /2 MB/)).toBe(true);
    expect(has(errs, /exceeds 1 MB/)).toBe(false);
  });

  it("rejects /workspace/workflow/scripts/x.py when absent", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), read(join(dir, "SKILL.md")) + "\nRun `python /workspace/workflow/scripts/x.py`.\n");
    expect(has(validateTemplate(dir), /scripts\/x\.py/)).toBe(true);
    mkdirSync(join(dir, "scripts"));
    writeFileSync(join(dir, "scripts/x.py"), "print(1)\n");
    expect(validateTemplate(dir)).toEqual([]);
  });

  it("rejects needs.secrets != frontmatter secrets", () => {
    const [, dir] = fixture();
    editJson(join(dir, "template.json"), (j) => (j.needs.secrets = ["API_KEY"]));
    expect(has(validateTemplate(dir), /secrets/)).toBe(true);
  });

  it("rejects needs.connections != frontmatter connections", () => {
    const [, dir] = fixture();
    editJson(join(dir, "template.json"), (j) => (j.needs.connections = ["gmail"]));
    expect(has(validateTemplate(dir), /connections/)).toBe(true);
  });

  it("rejects em-dash", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), read(join(dir, "SKILL.md")) + "\nA line — with a dash.\n");
    expect(has(validateTemplate(dir), /em-dash/)).toBe(true);
    const [, d2] = fixture();
    editJson(join(d2, "template.json"), (j) => (j.summary = "a — b"));
    expect(has(validateTemplate(d2), /em-dash/)).toBe(true);
  });

  it("rejects licence outside allowlist", () => {
    const [, dir] = fixture();
    editJson(join(dir, "template.json"), (j) => (j.source = { name: "x", repo: "a/b", path: "p", license: "GPL-3.0" }));
    expect(has(validateTemplate(dir), /licen[cs]e/i)).toBe(true);
    editJson(join(dir, "template.json"), (j) => (j.source.license = "MIT"));
    expect(validateTemplate(dir)).toEqual([]);
  });

  it("rejects /workspace/inputs/ inside a fenced code block", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), read(join(dir, "SKILL.md")) + "\n```bash\nls /workspace/inputs/\n```\n");
    expect(has(validateTemplate(dir), /fenced/)).toBe(true);
  });

  it("rejects /workspace/<other>/ prefix", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "SKILL.md"), read(join(dir, "SKILL.md")) + "\nWrite to /workspace/tmp/notes.txt.\n");
    expect(has(validateTemplate(dir), /\/workspace\/tmp\/notes\.txt/)).toBe(true);
  });

  it("rejects em-dash in any text file", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "evals/evals.json"), JSON.stringify({ evals: [{ prompt: "a \u2014 b", files: [], expectations: [] }] }));
    expect(has(validateTemplate(dir), /evals\/evals\.json contains an em-dash/)).toBe(true);
    const [, d2] = fixture();
    mkdirSync(join(d2, "references"));
    writeFileSync(join(d2, "references/x.md"), "a \u2014 b\n");
    expect(has(validateTemplate(d2), /references\/x\.md contains an em-dash/)).toBe(true);
  });

  it("applies the workspace path rules to references/*.md", () => {
    const [, dir] = fixture();
    mkdirSync(join(dir, "references"));
    writeFileSync(join(dir, "references/x.md"), "See /workspace/tmp/a.txt\n\n```\nls /workspace/inputs/\n```\n");
    const errs = validateTemplate(dir);
    expect(has(errs, /references\/x\.md: \/workspace\/tmp\/a\.txt/)).toBe(true);
    expect(has(errs, /references\/x\.md: .*fenced/)).toBe(true);
  });

  it("rejects unsafe file names and case-only duplicates", () => {
    const [, dir] = fixture();
    writeFileSync(join(dir, "my file.txt"), "x");
    expect(has(validateTemplate(dir), /my file\.txt.*letters, digits/)).toBe(true);
    expect(caseClashes(["samples/A.txt", "samples/a.txt", "b.txt"])).toHaveLength(1);
    expect(caseClashes(["a.txt", "b.txt"])).toEqual([]);
    const [, d3] = fixture();
    writeFileSync(join(d3, "evals/evals.json"), JSON.stringify({ evals: [{ prompt: "p", files: ["a b.txt"], expectations: [] }] }));
    expect(has(validateTemplate(d3), /letters, digits/)).toBe(true);
  });

  it("rejects /workspace/inputs in scripts and inline code spans", () => {
    const [, dir] = fixture();
    mkdirSync(join(dir, "scripts"), { recursive: true });
    writeFileSync(join(dir, "scripts/x.py"), 'open("/workspace/inputs/a.txt")\n');
    expect(has(validateTemplate(dir), /scripts\/x\.py.*\/workspace\/inputs.*prose/)).toBe(true);
    const [, d2] = fixture();
    const md = read(join(d2, "SKILL.md"));
    writeFileSync(join(d2, "SKILL.md"), md + "\nRead `/workspace/inputs/a.txt` first.\n");
    expect(has(validateTemplate(d2), /inline code span.*prose/)).toBe(true);
  });

  it("requires fetch_site.py copies to be identical", () => {
    const [root, dir] = fixture("one");
    const mk = (d: string, body: string) => {
      mkdirSync(join(d, "scripts"), { recursive: true });
      writeFileSync(join(d, "scripts/fetch_site.py"), body);
    };
    mk(dir, "a\n");
    const two = join(root, "templates", "two");
    mkdirSync(two, { recursive: true });
    mk(two, "b\n");
    const out = validateAll(root).find((r) => r.slug === "two")!;
    expect(has(out.errors, /fetch_site\.py differs/)).toBe(true);
  });
});
