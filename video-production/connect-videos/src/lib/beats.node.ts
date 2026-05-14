import { readFileSync } from "node:fs";
import { parseDefaults, type Defaults } from "./beats";

export * from "./beats";

export function loadDefaults(path: string): Defaults {
  return parseDefaults(readFileSync(path, "utf8"));
}
