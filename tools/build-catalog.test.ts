import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCatalog, writeCatalog } from "./build-catalog";
import { fixture } from "./test-helpers";

describe("buildCatalog", () => {
  it("lists every file but template.json with size and sha256", () => {
    const [root, dir] = fixture();
    const cat = buildCatalog(root, "abc123");
    expect(cat.version).toBe(1);
    expect(cat.commit).toBe("abc123");
    expect(new Date(cat.builtAt).toString()).not.toBe("Invalid Date");
    const t = cat.templates[0];
    expect(t.files.map((f) => f.path)).toEqual(["SKILL.md", "evals/evals.json", "samples/hello.txt"]);
    const skill = readFileSync(join(dir, "SKILL.md"));
    expect(t.files[0]).toEqual({ path: "SKILL.md", size: skill.length, sha256: createHash("sha256").update(skill).digest("hex") });
    expect(t.takes).toBe("One text file");
    expect(cat.categories[0]).toEqual({ id: "documents", title: "Documents", order: 1 });
  });

  it("reads step titles", () => {
    const [root] = fixture();
    expect(buildCatalog(root, "x").templates[0].steps).toEqual(["Read the file", "Write the summary"]);
  });

  it("sorts templates by category order then title", () => {
    const [root, dir] = fixture();
    const mk = (slug: string, title: string, category: string) => {
      const d = join(root, "templates", slug);
      mkdirSync(d, { recursive: true });
      writeFileSync(join(d, "SKILL.md"), readFileSync(join(dir, "SKILL.md")));
      const j = JSON.parse(readFileSync(join(dir, "template.json"), "utf8"));
      writeFileSync(join(d, "template.json"), JSON.stringify({ ...j, slug, title, category }));
    };
    mk("b-sales", "Beta", "sales");
    mk("a-sales", "Alpha", "sales");
    mk("z-legal", "Zed", "legal");
    expect(buildCatalog(root, "x").templates.map((t) => t.slug)).toEqual(["hello-template", "z-legal", "a-sales", "b-sales"]);
  });

  it("leaves catalog.json untouched when only the commit differs", () => {
    const [root, dir] = fixture();
    expect(writeCatalog(root, "c1")).toBe(true);
    const first = readFileSync(join(root, "catalog.json"), "utf8");
    expect(writeCatalog(root, "c2")).toBe(false);
    expect(readFileSync(join(root, "catalog.json"), "utf8")).toBe(first);
    writeFileSync(join(dir, "samples/hello.txt"), "changed\n");
    expect(writeCatalog(root, "c3")).toBe(true);
    expect(JSON.parse(readFileSync(join(root, "catalog.json"), "utf8")).commit).toBe("c3");
  });
});
