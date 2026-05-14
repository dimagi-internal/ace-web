#!/usr/bin/env tsx
/**
 * drive-fetch.ts — decode a Drive MCP tool-result JSON into the underlying
 * binary file. Works by consuming the file the MCP transport already wrote
 * to disk (when a binary download exceeds the inline token budget), so this
 * script never has to talk to Google Drive itself.
 *
 * Workflow:
 *   1. From the assistant context, call drive_download_binary(fileId).
 *      The MCP transport will write a JSON tool-result to a known path.
 *   2. Invoke this script with that path and the desired output:
 *        npm run drive-fetch -- --in=<tool-result.txt> --out=<dest.mp4>
 *      (Or pass --auto-name and the script will derive a kebab-case
 *      filename from the JSON's "name" field, dropped into <out-dir>.)
 *   3. Verifies the decoded byte count matches the JSON's "size" field.
 *
 * Cap: V8 string max (~500MB). Files larger than that need to be downloaded
 * via the Drive web UI manually.
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

interface ToolResult {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  content_base64: string;
}

interface CliArgs {
  in: string;
  out?: string;
  outDir?: string;
  autoName: boolean;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const inPath = args.find((a) => a.startsWith("--in="))?.slice("--in=".length);
  const outPath = args.find((a) => a.startsWith("--out="))?.slice("--out=".length);
  const outDir = args.find((a) => a.startsWith("--out-dir="))?.slice("--out-dir=".length);
  const autoName = args.includes("--auto-name");
  if (!inPath || (!outPath && !(autoName && outDir))) {
    console.error(
      "Usage:\n  npm run drive-fetch -- --in=<tool-result.txt> --out=<dest>\n  npm run drive-fetch -- --in=<tool-result.txt> --out-dir=<dir> --auto-name"
    );
    process.exit(2);
  }
  return { in: inPath, out: outPath, outDir, autoName };
}

function kebab(name: string): string {
  return name.replace(/\s+/g, "-").replace(/[^a-zA-Z0-9._-]/g, "-");
}

function extForMime(mime: string): string {
  const m: Record<string, string> = {
    "video/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
  };
  return m[mime] ?? "";
}

function main() {
  const cli = parseArgs();
  const result: ToolResult = JSON.parse(readFileSync(cli.in, "utf8"));

  let outPath: string;
  if (cli.autoName) {
    const base = kebab(result.name);
    // If name doesn't carry an extension, append one from the mime type.
    const withExt = /\.[a-zA-Z0-9]{2,4}$/.test(base) ? base : base + extForMime(result.mimeType);
    outPath = path.join(cli.outDir!, withExt);
  } else {
    outPath = cli.out!;
  }

  const buf = Buffer.from(result.content_base64, "base64");
  if (buf.length !== result.size) {
    console.warn(
      `WARN: decoded byte count ${buf.length} != claimed size ${result.size} for ${result.name}`
    );
  }
  writeFileSync(outPath, buf);
  console.log(`wrote ${outPath} (${buf.length} bytes; mime=${result.mimeType}; name=${JSON.stringify(result.name)})`);
}

main();
