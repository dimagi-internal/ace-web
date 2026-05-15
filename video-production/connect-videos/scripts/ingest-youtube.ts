#!/usr/bin/env tsx
import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

interface CliArgs {
  url: string;
  out: string;
  owned: boolean;
  transcript: boolean;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const url = args.find((a) => a.startsWith("--url="))?.slice("--url=".length);
  const out = args.find((a) => a.startsWith("--out="))?.slice("--out=".length);
  const owned = args.includes("--owned");
  const transcript = args.includes("--transcript");
  if (!url || !out) {
    console.error(
      "Usage: npm run ingest -- --url=<youtube_url> --out=assets/programs/<slug>/ --owned [--transcript]"
    );
    process.exit(2);
  }
  return { url, out, owned, transcript };
}

function main() {
  const { url, out, owned, transcript } = parseArgs();
  if (!owned) {
    console.error(
      "Refusing to download: pass --owned to confirm this YouTube URL is a Dimagi-owned upload. Third-party footage cannot be embedded in published videos."
    );
    process.exit(1);
  }
  mkdirSync(out, { recursive: true });
  const videoOut = path.join(out, "%(id)s.%(ext)s");
  execSync(`yt-dlp -f "bv*[height<=1080]+ba/b" -o ${JSON.stringify(videoOut)} ${JSON.stringify(url)}`, {
    stdio: "inherit",
  });
  if (transcript) {
    execSync(
      `yt-dlp --write-auto-sub --sub-lang en --skip-download -o ${JSON.stringify(videoOut)} ${JSON.stringify(url)}`,
      { stdio: "inherit" }
    );
  }
  console.log(`Ingested into ${out}.`);
}

main();
