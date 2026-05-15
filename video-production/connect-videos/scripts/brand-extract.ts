#!/usr/bin/env tsx

async function main() {
  const resp = await fetch("https://labs.connect.dimagi.com/");
  if (!resp.ok) {
    console.error(`HTTP ${resp.status}`);
    process.exit(1);
  }
  const html = await resp.text();
  const hexes = Array.from(new Set(html.match(/#[0-9a-fA-F]{6}\b/g) ?? []));
  const fonts = Array.from(new Set(html.match(/font-family:\s*([^;"'}]+)/g) ?? []));
  console.log("Hex colors found in markup:");
  hexes.forEach((h) => console.log("  ", h));
  console.log("\nFont-family declarations:");
  fonts.forEach((f) => console.log("  ", f));
  console.log(
    "\nUpdate connect-videos/src/theme.ts manually with any tokens you want to adopt."
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
