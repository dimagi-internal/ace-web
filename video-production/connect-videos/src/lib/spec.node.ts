import { readFileSync } from "node:fs";
import { parseProgramSpec, type ProgramSpec } from "./spec";

export * from "./spec";

export function loadProgramSpec(
  pathOrYaml: string,
  opts: { fromString?: boolean } = {}
): ProgramSpec {
  const raw = opts.fromString ? pathOrYaml : readFileSync(pathOrYaml, "utf8");
  return parseProgramSpec(raw);
}
