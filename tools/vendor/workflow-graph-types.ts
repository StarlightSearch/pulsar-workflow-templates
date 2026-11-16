/**
 * Vendored from StarlightSearch/Pulsar packages/core/src/workflow-graph/source-types.ts
 * at commit 8029f46b: only `OverviewStep`, the one type the vendored parser imports.
 */
export interface OverviewStep {
  id: string;
  title: string;
  detail: string;
  kind: "action" | "decision" | "loop";
  branches?: { when: string; then: string }[];
  children?: OverviewStep[];
  agents?: { name: string; role: string }[];
  maxPasses?: number;
}
