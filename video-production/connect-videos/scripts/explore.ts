#!/usr/bin/env tsx
/**
 * explore.ts — build the clip-explorer page for a program and serve
 * it on a local HTTP port so the browser can play the local MP4s
 * (file:// blocks cross-origin media in Chrome).
 *
 * Usage: npm run explore -- --program=chc [--port=8765]
 */

import { spawnSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { createReadStream } from "node:fs";
import { promises as fs } from "node:fs";
import { parseDocument } from "yaml";

interface CliArgs {
  program: string;
  port: number;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.slice("--program=".length);
  const portArg = args.find((a) => a.startsWith("--port="))?.slice("--port=".length);
  if (!program) {
    console.error("Usage: npm run explore -- --program=<slug> [--port=8765]");
    process.exit(2);
  }
  return { program, port: portArg ? Number(portArg) : 8765 };
}

function build(program: string) {
  const r = spawnSync("npx", ["tsx", "scripts/build-clip-explorer.ts", `--program=${program}`], {
    stdio: "inherit",
  });
  if (r.status !== 0) {
    process.exit(r.status ?? 1);
  }
}

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mkv": "video/x-matroska",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

interface LibraryJsonEntry {
  alias: string;
  sourcePath: string | null;
  dur: number | null;
  res: string | null;
  usedIn: string[];
}

async function buildLibraryJson(rootDir: string, program: string): Promise<{ entries: LibraryJsonEntry[] }> {
  const indexHtml = await fs.readFile(path.join(rootDir, "index.html"), "utf8").catch(() => "");
  // Parse the drawer-card data out of library.html which we already built —
  // it's our source-of-truth for media paths + usedIn tags.
  const libHtml = await fs.readFile(path.join(rootDir, "library.html"), "utf8").catch(() => "");
  // Lazy: regex-extract the lib-card blocks. Each has the alias as @<name>,
  // optional video src under media/, optional duration+res in lib-meta, and
  // used-in tags from .lib-tag.used-in entries.
  const entries: LibraryJsonEntry[] = [];
  const cardRegex = /<div class="lib-card">([\s\S]*?)<\/div>\s*<\/div>(?=\s*(<div class="lib-card"|<\/div>))/g;
  let m: RegExpExecArray | null;
  while ((m = cardRegex.exec(libHtml))) {
    const block = m[1];
    const aliasMatch = block.match(/<h3>@([^<]+)<\/h3>/);
    if (!aliasMatch) continue;
    const alias = aliasMatch[1].trim();
    const srcMatch = block.match(/<video src="([^"]+)"/);
    const sourcePath = srcMatch ? srcMatch[1] : null;
    const metaMatch = block.match(/<span>([\d.]+)s · ([\dx]+)<\/span>/);
    const dur = metaMatch ? parseFloat(metaMatch[1]) : null;
    const res = metaMatch ? metaMatch[2] : null;
    const usedIn: string[] = [];
    const usedRe = /lib-tag used-in[^>]*>([^<]+)</g;
    let u: RegExpExecArray | null;
    while ((u = usedRe.exec(block))) usedIn.push(u[1].trim());
    entries.push({ alias, sourcePath, dur, res, usedIn });
  }
  void indexHtml;
  void program;
  return { entries };
}

async function serve(rootDir: string, port: number, program: string) {
  const feedbackPath = path.join(rootDir, "feedback.md");
  const yamlPath = path.resolve("programs", `${program}.yaml`);

  async function applyEdit(body: {
    op: string;
    kind?: string;
    index?: number;
    start_seconds?: number;
    duration_seconds?: number;
    beatId?: string;
    text?: string;
    alias?: string;
  }): Promise<{ ok: boolean; message: string }> {
    const text = await fs.readFile(yamlPath, "utf8");
    const doc = parseDocument(text);

    const clipPath = (kind: string | undefined, index: number) =>
      kind === "scene-clip" ? ["scene", "clips", index] : ["product", "beats", index];

    if (body.op === "set-clip-start" && typeof body.index === "number" && typeof body.start_seconds === "number") {
      const p = clipPath(body.kind, body.index);
      const node = doc.getIn(p) as unknown;
      if (typeof node === "string") {
        doc.setIn(p, { asset: node, start_seconds: body.start_seconds });
      } else if (node && typeof node === "object") {
        doc.setIn([...p, "start_seconds"], body.start_seconds);
      } else {
        return { ok: false, message: `Could not find ${body.kind}[${body.index}]` };
      }
      await fs.writeFile(yamlPath, doc.toString(), "utf8");
      return { ok: true, message: `Set ${body.kind}[${body.index}].start_seconds = ${body.start_seconds}` };
    }

    if (body.op === "set-clip-trim"
        && typeof body.index === "number"
        && typeof body.start_seconds === "number"
        && typeof body.duration_seconds === "number") {
      const p = clipPath(body.kind, body.index);
      const node = doc.getIn(p) as unknown;
      // Promote bare-string clip refs into object form on first trim.
      if (typeof node === "string") {
        doc.setIn(p, {
          asset: node,
          start_seconds: body.start_seconds,
          duration_seconds: body.duration_seconds,
        });
      } else if (node && typeof node === "object") {
        doc.setIn([...p, "start_seconds"], body.start_seconds);
        doc.setIn([...p, "duration_seconds"], body.duration_seconds);
      } else {
        return { ok: false, message: `Could not find ${body.kind}[${body.index}]` };
      }
      await fs.writeFile(yamlPath, doc.toString(), "utf8");
      return { ok: true, message: `Set ${body.kind}[${body.index}] trim window` };
    }

    if (body.op === "set-clip-asset" && typeof body.index === "number" && typeof body.alias === "string") {
      const p = clipPath(body.kind, body.index);
      const node = doc.getIn(p) as unknown;
      const newRef = `@${body.alias}`;
      if (typeof node === "string") {
        // For scene clips a bare string is the legacy compact form; preserve
        // that shape on swap. For product beats, the asset is a nested key.
        if (body.kind === "scene-clip") {
          doc.setIn(p, newRef);
        } else {
          doc.setIn([...p, "asset"], newRef);
        }
      } else if (node && typeof node === "object") {
        doc.setIn([...p, "asset"], newRef);
      } else {
        return { ok: false, message: `Could not find ${body.kind}[${body.index}]` };
      }
      await fs.writeFile(yamlPath, doc.toString(), "utf8");
      return { ok: true, message: `Swapped ${body.kind}[${body.index}] -> @${body.alias}` };
    }

    if (body.op === "set-narration" && body.beatId && typeof body.text === "string") {
      doc.setIn(["narration", "by_beat", body.beatId], body.text);
      await fs.writeFile(yamlPath, doc.toString(), "utf8");
      return { ok: true, message: `Updated narration.by_beat.${body.beatId}` };
    }
    return { ok: false, message: `Unknown op or missing args: ${JSON.stringify(body)}` };
  }

  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", `http://localhost:${port}`);
      const method = (req.method ?? "GET").toUpperCase();

      // /library.json — structured manifest for the drawer UI
      if (url.pathname === "/library.json") {
        const libData = await buildLibraryJson(rootDir, program);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify(libData));
        return;
      }

      // /edit — POST to update the program's YAML (and optionally re-render)
      if (url.pathname === "/edit") {
        if (method !== "POST") { res.writeHead(405); res.end(); return; }
        const chunks: Buffer[] = [];
        for await (const c of req) chunks.push(c as Buffer);
        const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        const result = await applyEdit(body);
        if (!result.ok) {
          res.writeHead(400, { "content-type": "application/json" });
          res.end(JSON.stringify(result));
          return;
        }
        // For asset swaps we may need to materialize a new clip into
        // public/assets/programs/<slug>/ first. hydrate is idempotent.
        const needsHydrate = body.op === "set-clip-asset";
        const chain = needsHydrate
          ? "npm run hydrate -- --program=" + program + " && npm run build-clip-explorer -- --program=" + program + " && npm run render -- --program=" + program + " --draft"
          : "npm run render -- --program=" + program + " --draft && npm run build-clip-explorer -- --program=" + program;
        spawn("sh", ["-c", chain], { stdio: "ignore", detached: true }).unref();
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: true, rerendered: false, message: result.message + " — re-render kicked off in background" }));
        return;
      }

      // /feedback — POST to append, GET to read
      if (url.pathname === "/feedback") {
        if (method === "POST") {
          const chunks: Buffer[] = [];
          for await (const c of req) chunks.push(c as Buffer);
          const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          const ts = new Date().toISOString().replace("T", " ").slice(0, 19);
          const scope = body.scope === "beat" ? `beat:${body.beatId}` : "global";
          const timeBit = body.timestampSec != null ? ` (video t=${Number(body.timestampSec).toFixed(1)}s)` : "";
          const line = `\n## [${ts}] ${scope}${timeBit}\n\n${body.note}\n`;
          await fs.appendFile(feedbackPath, line, "utf8");
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({ ok: true, timestamp: ts }));
          return;
        }
        if (method === "GET") {
          const data = await fs.readFile(feedbackPath, "utf8").catch(() => "");
          res.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
          res.end(data);
          return;
        }
        res.writeHead(405); res.end("method not allowed"); return;
      }

      let p = decodeURIComponent(url.pathname);
      if (p === "/") p = "/index.html";
      const filePath = path.join(rootDir, p);
      const rel = path.relative(rootDir, filePath);
      if (rel.startsWith("..") || path.isAbsolute(rel)) {
        res.writeHead(403); res.end("forbidden"); return;
      }
      const stat = await fs.stat(filePath).catch(() => null);
      if (!stat || !stat.isFile()) {
        res.writeHead(404); res.end("not found"); return;
      }
      const ext = path.extname(filePath).toLowerCase();
      const mime = MIME[ext] ?? "application/octet-stream";

      // Range support for video scrubbing.
      const range = req.headers.range;
      const size = stat.size;
      if (range && /^bytes=\d*-\d*$/.test(range)) {
        const [s, e] = range.replace("bytes=", "").split("-");
        const start = s ? Number(s) : 0;
        const end = e ? Number(e) : size - 1;
        const chunkSize = end - start + 1;
        res.writeHead(206, {
          "Content-Range": `bytes ${start}-${end}/${size}`,
          "Accept-Ranges": "bytes",
          "Content-Length": chunkSize,
          "Content-Type": mime,
        });
        createReadStream(filePath, { start, end }).pipe(res);
      } else {
        res.writeHead(200, {
          "Content-Length": size,
          "Accept-Ranges": "bytes",
          "Content-Type": mime,
        });
        createReadStream(filePath).pipe(res);
      }
    } catch (e) {
      res.writeHead(500);
      res.end(`error: ${(e as Error).message}`);
    }
  });
  await new Promise<void>((resolve) => server.listen(port, resolve));
  return server;
}

async function main() {
  const cli = parseArgs();
  build(cli.program);
  const outDir = path.resolve("out", "clip-explorer", cli.program);
  if (!existsSync(outDir)) {
    console.error(`Expected ${outDir} after build; not found.`);
    process.exit(1);
  }
  const server = await serve(outDir, cli.port, cli.program);
  const url = `http://localhost:${cli.port}/`;
  console.log(`\nClip explorer running at ${url}`);
  console.log("Press Ctrl-C to stop.\n");
  // Open in default browser
  spawn("open", [url], { stdio: "ignore", detached: true });

  // Wait forever (until interrupted)
  process.on("SIGINT", () => {
    server.close();
    console.log("\nShutting down clip explorer.");
    process.exit(0);
  });
}

main();
