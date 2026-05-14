# Connect Program Videos POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Remotion-based, template-driven pipeline that renders a 60-second Mother-Baby Wellness video for `labs.connect.dimagi.com`, with infrastructure that generalizes to all 10 Connect programs.

**Architecture:** A single Remotion project (`connect-videos/`) registers a `ProgramVideo` composition stitched from three shared compositions: `<Intro/>` (15s), `<ProgramBody/>` (37s, props-driven), `<Outro/>` (8s). Per-program data lives in `programs/<slug>.yaml`. Beat durations are data (merged from `_defaults.yaml` + per-program overrides), so timing can be re-tuned without code changes. A small pipeline orchestrates LLM narration drafting (Anthropic), AI voiceover (ElevenLabs, hash-cached), caption alignment, and Remotion render into `out/<slug>-v<git-sha>.mp4`.

**Tech Stack:** Remotion 4.x, React 18, TypeScript 5, Vite (via Remotion), Vitest, `yaml`, `@anthropic-ai/sdk`, `elevenlabs` (REST client), `@remotion/captions`, `yt-dlp` (system), `ffmpeg` (system).

**Reference spec:** `docs/superpowers/specs/2026-05-13-connect-program-videos-poc-design.md`

---

## File map

| Path | Purpose |
|---|---|
| `connect-videos/package.json` | npm scripts and deps |
| `connect-videos/tsconfig.json` | TS config (target ES2022, jsx react-jsx) |
| `connect-videos/remotion.config.ts` | Remotion render defaults |
| `connect-videos/vitest.config.ts` | Vitest config with jsdom |
| `connect-videos/src/Root.tsx` | Registers `ProgramVideo` composition |
| `connect-videos/src/theme.ts` | Brand colors + typography |
| `connect-videos/src/lib/spec.ts` | Typed `ProgramSpec`, YAML loader, validation |
| `connect-videos/src/lib/beats.ts` | Merges defaults + overrides, computes start frames |
| `connect-videos/src/lib/narration.ts` | Anthropic prompt + script generator |
| `connect-videos/src/lib/voiceover.ts` | ElevenLabs client with sha256 cache |
| `connect-videos/src/lib/captions.ts` | Whisper alignment with estimated-alignment fallback |
| `connect-videos/src/components/StatCard.tsx` | Big-number stat card with caption + animation |
| `connect-videos/src/components/Lower3rd.tsx` | Country / program lower-third |
| `connect-videos/src/components/KenBurns.tsx` | Photo with slow zoom/pan |
| `connect-videos/src/components/AppScreen.tsx` | Phone-frame wrapper for app recordings |
| `connect-videos/src/components/CycleStep.tsx` | One step of Learn/Deliver/Verify/Pay |
| `connect-videos/src/components/CaptionBar.tsx` | On-screen burned-in caption bar |
| `connect-videos/src/compositions/Intro.tsx` | 15s shared intro |
| `connect-videos/src/compositions/ProgramBody.tsx` | 37s per-program body |
| `connect-videos/src/compositions/Outro.tsx` | 8s shared outro |
| `connect-videos/programs/_defaults.yaml` | Default beat list, fps, voice config |
| `connect-videos/programs/mbw.yaml` | MBW spec, populated from labs site |
| `connect-videos/assets/programs/mbw/` | Placeholder MBW assets |
| `connect-videos/scripts/render.ts` | Orchestrates load → narrate-check → voice → caption → remotion render |
| `connect-videos/scripts/narrate.ts` | CLI to draft narration via Anthropic into YAML |
| `connect-videos/scripts/ingest-youtube.ts` | `yt-dlp` wrapper for Dimagi-owned references |
| `connect-videos/scripts/brand-extract.ts` | Scrape brand assets from labs.connect.dimagi.com |
| `connect-videos/out/` | Final MP4s (gitignored) |
| `connect-videos/.gitignore` | Ignore `node_modules`, `out/`, `assets/audio/`, etc. |
| `connect-videos/README.md` | How to render, narrate, ingest |

---

### Task 1: Bootstrap the Remotion project

**Files:**
- Create: `connect-videos/package.json`
- Create: `connect-videos/tsconfig.json`
- Create: `connect-videos/remotion.config.ts`
- Create: `connect-videos/vitest.config.ts`
- Create: `connect-videos/.gitignore`
- Create: `connect-videos/src/Root.tsx`
- Create: `connect-videos/README.md`

- [ ] **Step 1: Create the connect-videos directory and init files**

Run: `mkdir -p connect-videos/{src/{lib,components,compositions},programs,assets/{shared,audio,programs/mbw},scripts,out}`

- [ ] **Step 2: Write `connect-videos/package.json`**

```json
{
  "name": "connect-videos",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "start": "remotion studio src/Root.tsx",
    "render": "tsx scripts/render.ts",
    "narrate": "tsx scripts/narrate.ts",
    "ingest": "tsx scripts/ingest-youtube.ts",
    "brand-extract": "tsx scripts/brand-extract.ts",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@anthropic-ai/sdk": "^0.30.0",
    "@remotion/bundler": "^4.0.0",
    "@remotion/captions": "^4.0.0",
    "@remotion/cli": "^4.0.0",
    "@remotion/renderer": "^4.0.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "remotion": "^4.0.0",
    "yaml": "^2.5.0",
    "zod": "4.3.6"
  },
  "devDependencies": {
    "@testing-library/react": "^16.0.0",
    "@types/node": "^22.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "tsx": "^4.19.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 3: Write `connect-videos/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "allowImportingTsExtensions": false,
    "noEmit": true,
    "lib": ["ES2022", "DOM"],
    "types": ["node", "vitest/globals"]
  },
  "include": ["src", "scripts", "vitest.config.ts", "remotion.config.ts"]
}
```

- [ ] **Step 4: Write `connect-videos/remotion.config.ts`**

```ts
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setCodec("h264");
Config.setCrf(22);
Config.setPixelFormat("yuv420p");
Config.setConcurrency(null); // use all cores
Config.setOverwriteOutput(true);
```

- [ ] **Step 5: Write `connect-videos/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

- [ ] **Step 6: Write `connect-videos/.gitignore`**

```
node_modules/
out/
assets/audio/
.remotion/
*.log
.env
.env.local
```

- [ ] **Step 7: Write `connect-videos/src/Root.tsx` (minimal placeholder for now)**

```tsx
import { Composition } from "remotion";

const Hello: React.FC = () => <div style={{ flex: 1, background: "white" }} />;

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Hello"
    component={Hello}
    durationInFrames={30}
    fps={30}
    width={1920}
    height={1080}
  />
);
```

- [ ] **Step 8: Write `connect-videos/README.md` (minimal)**

```markdown
# connect-videos

Template-driven 60-second videos for Connect programs on labs.connect.dimagi.com.

## Setup

\`\`\`
npm install
\`\`\`

## Commands

- \`npm start\` — open Remotion Studio for live preview
- \`npm run narrate -- --program=mbw\` — draft narration via Anthropic into the YAML
- \`npm run render -- --program=mbw\` — full pipeline → out/mbw-v<sha>.mp4
- \`npm test\` — run unit tests

See \`docs/superpowers/specs/2026-05-13-connect-program-videos-poc-design.md\` for the design.
```

- [ ] **Step 9: Install dependencies and verify**

Run: `cd connect-videos && npm install`
Expected: install succeeds; `node_modules/` populated.

Run: `cd connect-videos && npm run typecheck`
Expected: PASS (no type errors).

Run: `cd connect-videos && npm start` (just to confirm Remotion Studio launches; Ctrl-C after seeing the URL)
Expected: prints `Studio running at http://localhost:3000`.

- [ ] **Step 10: Commit**

```bash
git add connect-videos/
git commit -m "feat(videos): bootstrap Remotion project scaffold"
```

---

### Task 2: Theme module

**Files:**
- Create: `connect-videos/src/theme.ts`
- Create: `connect-videos/src/theme.test.ts`

Brand values come from labs.connect.dimagi.com (off-white background, dark charcoal text, emerald/teal accent). `brand-extract.ts` will refine these later (Task 14); for now they're hardcoded.

- [ ] **Step 1: Write the failing test `connect-videos/src/theme.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import { theme } from "./theme";

describe("theme", () => {
  it("exposes a six-character hex for every color token", () => {
    for (const [key, value] of Object.entries(theme.colors)) {
      expect(value, `${key} should be #RRGGBB`).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("has a primary accent color used by stat cards", () => {
    expect(theme.colors.accent).toBeDefined();
  });

  it("provides a sans-serif font stack", () => {
    expect(theme.fonts.sans).toMatch(/sans-serif/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/theme.test.ts`
Expected: FAIL ("Cannot find module './theme'").

- [ ] **Step 3: Write `connect-videos/src/theme.ts`**

```ts
export const theme = {
  colors: {
    background: "#FAFAF7",
    foreground: "#1A1F2C",
    muted: "#5A6072",
    accent: "#1F8F6F",
    accentDark: "#10684F",
    surface: "#FFFFFF",
    captionBg: "#1A1F2C",
    captionFg: "#FFFFFF",
  },
  fonts: {
    sans: "Inter, system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif",
    display: "Inter, system-ui, sans-serif",
  },
  radii: { sm: 6, md: 12, lg: 24 },
  spacing: { xs: 8, sm: 16, md: 24, lg: 48, xl: 96 },
} as const;

export type Theme = typeof theme;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/theme.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add connect-videos/src/theme.ts connect-videos/src/theme.test.ts
git commit -m "feat(videos): add theme tokens with hex/font validation tests"
```

---

### Task 3: ProgramSpec types and YAML parser

**Files:**
- Create: `connect-videos/src/lib/spec.ts`
- Create: `connect-videos/src/lib/spec.test.ts`
- Create: `connect-videos/src/lib/__fixtures__/valid.yaml`
- Create: `connect-videos/src/lib/__fixtures__/missing-impact.yaml`

The parser uses Zod to validate, surfacing exact error paths on misshapen specs.

- [ ] **Step 1: Write fixture `connect-videos/src/lib/__fixtures__/valid.yaml`**

```yaml
slug: demo
name: Demo Program
country_focus: Demo Country
status: Active
tagline: "Demo tagline."
program_url: https://example.com
scene:
  clips:
    - assets/programs/demo/scene-01.jpg
  lower_third: "Demo · 2026"
problem:
  big: "50%"
  caption: "Problem caption."
  source: "Source 2024"
product:
  beats:
    - asset: assets/programs/demo/beat-01.mp4
      caption: "Beat 1"
impact:
  - big: "$1M"
    caption: "Funding"
  - big: "1,000"
    caption: "Targets"
narration:
  generator: manual
  prompt_version: v1
  script: "Sample narration."
voice:
  provider: elevenlabs
  voice_id: abc123
  model: eleven_turbo_v2
```

- [ ] **Step 2: Write fixture `connect-videos/src/lib/__fixtures__/missing-impact.yaml`**

```yaml
slug: demo
name: Demo Program
country_focus: Demo Country
status: Active
tagline: "Demo tagline."
program_url: https://example.com
scene:
  clips: [assets/programs/demo/scene-01.jpg]
  lower_third: "Demo · 2026"
problem:
  big: "50%"
  caption: "Problem caption."
  source: "Source 2024"
product:
  beats:
    - asset: assets/programs/demo/beat-01.mp4
      caption: "Beat 1"
narration: { generator: manual, prompt_version: v1, script: "x" }
voice: { provider: elevenlabs, voice_id: abc123, model: eleven_turbo_v2 }
```

- [ ] **Step 3: Write the failing test `connect-videos/src/lib/spec.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import { loadProgramSpec, ProgramSpecError } from "./spec";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => path.join(here, "__fixtures__", name);

describe("loadProgramSpec", () => {
  it("parses a valid spec into a typed object", () => {
    const spec = loadProgramSpec(fixture("valid.yaml"));
    expect(spec.slug).toBe("demo");
    expect(spec.problem.big).toBe("50%");
    expect(spec.product.beats).toHaveLength(1);
    expect(spec.impact).toHaveLength(2);
  });

  it("throws ProgramSpecError with field path on missing impact", () => {
    expect(() => loadProgramSpec(fixture("missing-impact.yaml")))
      .toThrowError(/impact/);
  });

  it("rejects a product.beats array with more than 4 entries", () => {
    const badYaml = `
slug: demo
name: x
country_focus: x
status: x
tagline: x
program_url: https://x
scene: { clips: [a], lower_third: x }
problem: { big: "1", caption: x, source: x }
product:
  beats:
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
    - { asset: a, caption: b }
impact:
  - { big: "1", caption: x }
  - { big: "2", caption: y }
narration: { generator: manual, prompt_version: v1, script: x }
voice: { provider: elevenlabs, voice_id: a, model: eleven_turbo_v2 }
`;
    expect(() => loadProgramSpec(badYaml, { fromString: true }))
      .toThrowError(/product\.beats/);
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/lib/spec.test.ts`
Expected: FAIL ("Cannot find module './spec'").

- [ ] **Step 5: Write `connect-videos/src/lib/spec.ts`**

```ts
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { z } from "zod";

const BeatOverrideSchema = z.object({ seconds: z.number().positive() }).partial();

const ProductBeatSchema = z.object({
  asset: z.string().min(1),
  caption: z.string().min(1),
});

const StatSchema = z.object({
  big: z.string().min(1),
  caption: z.string().min(1),
  source: z.string().optional(),
});

export const ProgramSpecSchema = z.object({
  slug: z.string().regex(/^[a-z0-9-]+$/),
  name: z.string().min(1),
  country_focus: z.string().min(1),
  status: z.string().min(1),
  tagline: z.string().min(1),
  program_url: z.string().url(),
  beat_overrides: z.record(z.string(), BeatOverrideSchema).optional(),
  scene: z.object({
    clips: z.array(z.string().min(1)).min(1).max(6),
    lower_third: z.string().min(1),
  }),
  problem: StatSchema,
  product: z.object({
    beats: z.array(ProductBeatSchema).min(1).max(4),
  }),
  impact: z.array(StatSchema).min(2).max(3),
  narration: z.object({
    generator: z.enum(["manual", "anthropic"]),
    prompt_version: z.string().min(1),
    script: z.string(),
  }),
  voice: z.object({
    provider: z.enum(["elevenlabs", "none"]),
    voice_id: z.string().min(1),
    model: z.string().min(1),
  }),
});

export type ProgramSpec = z.infer<typeof ProgramSpecSchema>;

export class ProgramSpecError extends Error {
  constructor(message: string, public readonly issues: z.ZodIssue[] = []) {
    super(message);
    this.name = "ProgramSpecError";
  }
}

export function loadProgramSpec(
  pathOrYaml: string,
  opts: { fromString?: boolean } = {}
): ProgramSpec {
  const raw = opts.fromString ? pathOrYaml : readFileSync(pathOrYaml, "utf8");
  const parsed = parse(raw);
  const result = ProgramSpecSchema.safeParse(parsed);
  if (!result.success) {
    const detail = result.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ");
    throw new ProgramSpecError(`Invalid program spec: ${detail}`, result.error.issues);
  }
  return result.data;
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/lib/spec.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add connect-videos/src/lib/spec.ts connect-videos/src/lib/spec.test.ts connect-videos/src/lib/__fixtures__/
git commit -m "feat(videos): typed ProgramSpec loader with zod validation"
```

---

### Task 4: Default beats config + beat resolver

**Files:**
- Create: `connect-videos/programs/_defaults.yaml`
- Create: `connect-videos/src/lib/beats.ts`
- Create: `connect-videos/src/lib/beats.test.ts`

- [ ] **Step 1: Write `connect-videos/programs/_defaults.yaml`**

```yaml
fps: 30
total_seconds: 60
beats:
  - { id: hook,     kind: intro_hook,         seconds: 4 }
  - { id: cycle,    kind: intro_cycle,        seconds: 8 }
  - { id: handoff,  kind: intro_handoff,      seconds: 3 }
  - { id: scene,    kind: body_scene,         seconds: 7 }
  - { id: problem,  kind: body_problem_stat,  seconds: 10 }
  - { id: product,  kind: body_product_beats, seconds: 12 }
  - { id: impact,   kind: body_impact_stats,  seconds: 8 }
  - { id: cta,      kind: outro_cta,          seconds: 8 }
voice:
  provider: elevenlabs
  voice_id: "21m00Tcm4TlvDq8ikWAM"
  model: eleven_turbo_v2
```

- [ ] **Step 2: Write the failing test `connect-videos/src/lib/beats.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import { resolveBeats } from "./beats";

const defaults = {
  fps: 30,
  total_seconds: 60,
  beats: [
    { id: "hook",   kind: "intro_hook" as const,    seconds: 4 },
    { id: "cycle",  kind: "intro_cycle" as const,   seconds: 8 },
    { id: "scene",  kind: "body_scene" as const,    seconds: 40 },
    { id: "cta",    kind: "outro_cta" as const,     seconds: 8 },
  ],
};

describe("resolveBeats", () => {
  it("returns beats with start/end frames computed from defaults", () => {
    const resolved = resolveBeats(defaults, {});
    expect(resolved.fps).toBe(30);
    expect(resolved.totalFrames).toBe(60 * 30);
    expect(resolved.beats[0]).toMatchObject({ id: "hook", startFrame: 0, durationFrames: 120 });
    expect(resolved.beats[1]).toMatchObject({ id: "cycle", startFrame: 120, durationFrames: 240 });
    expect(resolved.beats[3]).toMatchObject({ id: "cta", startFrame: 1560, durationFrames: 240 });
  });

  it("applies per-beat overrides and rebalances if total still matches", () => {
    const resolved = resolveBeats(defaults, { scene: { seconds: 35 }, hook: { seconds: 9 } });
    const scene = resolved.beats.find((b) => b.id === "scene")!;
    const hook = resolved.beats.find((b) => b.id === "hook")!;
    expect(scene.durationFrames).toBe(35 * 30);
    expect(hook.durationFrames).toBe(9 * 30);
  });

  it("throws if overridden beats no longer sum to total_seconds", () => {
    expect(() => resolveBeats(defaults, { scene: { seconds: 50 } }))
      .toThrowError(/sum/);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/lib/beats.test.ts`
Expected: FAIL ("Cannot find module './beats'").

- [ ] **Step 4: Write `connect-videos/src/lib/beats.ts`**

```ts
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { z } from "zod";

export const BeatKind = z.enum([
  "intro_hook",
  "intro_cycle",
  "intro_handoff",
  "body_scene",
  "body_problem_stat",
  "body_product_beats",
  "body_impact_stats",
  "outro_cta",
]);
export type BeatKind = z.infer<typeof BeatKind>;

export const DefaultsSchema = z.object({
  fps: z.number().int().positive(),
  total_seconds: z.number().positive(),
  beats: z.array(
    z.object({ id: z.string(), kind: BeatKind, seconds: z.number().positive() })
  ).min(1),
  voice: z.object({
    provider: z.enum(["elevenlabs", "none"]),
    voice_id: z.string(),
    model: z.string(),
  }),
});
export type Defaults = z.infer<typeof DefaultsSchema>;

export type BeatOverrides = Record<string, { seconds?: number } | undefined>;

export interface ResolvedBeat {
  id: string;
  kind: BeatKind;
  seconds: number;
  startFrame: number;
  durationFrames: number;
}

export interface ResolvedTimeline {
  fps: number;
  totalFrames: number;
  beats: ResolvedBeat[];
}

export function loadDefaults(path: string): Defaults {
  const raw = readFileSync(path, "utf8");
  return DefaultsSchema.parse(parse(raw));
}

export function resolveBeats(
  defaults: Pick<Defaults, "fps" | "total_seconds" | "beats">,
  overrides: BeatOverrides
): ResolvedTimeline {
  const merged = defaults.beats.map((b) => ({
    ...b,
    seconds: overrides[b.id]?.seconds ?? b.seconds,
  }));
  const sum = merged.reduce((acc, b) => acc + b.seconds, 0);
  if (Math.abs(sum - defaults.total_seconds) > 0.001) {
    throw new Error(
      `Beat seconds sum to ${sum}, expected ${defaults.total_seconds}. Adjust overrides.`
    );
  }
  let cursor = 0;
  const beats: ResolvedBeat[] = merged.map((b) => {
    const durationFrames = Math.round(b.seconds * defaults.fps);
    const out: ResolvedBeat = {
      id: b.id,
      kind: b.kind,
      seconds: b.seconds,
      startFrame: cursor,
      durationFrames,
    };
    cursor += durationFrames;
    return out;
  });
  return { fps: defaults.fps, totalFrames: cursor, beats };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/lib/beats.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add connect-videos/programs/_defaults.yaml connect-videos/src/lib/beats.ts connect-videos/src/lib/beats.test.ts
git commit -m "feat(videos): beat resolver merges defaults + overrides into frame timeline"
```

---

### Task 5: Reusable visual primitives (Lower3rd, KenBurns, CaptionBar)

**Files:**
- Create: `connect-videos/src/components/Lower3rd.tsx`
- Create: `connect-videos/src/components/KenBurns.tsx`
- Create: `connect-videos/src/components/CaptionBar.tsx`
- Create: `connect-videos/src/components/Lower3rd.test.tsx`

Three smallest components first. The tests are render smoke tests; deeper visual verification happens at composition level.

- [ ] **Step 1: Write the failing test `connect-videos/src/components/Lower3rd.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Lower3rd } from "./Lower3rd";

describe("Lower3rd", () => {
  it("renders the provided text", () => {
    const { getByText } = render(<Lower3rd text="Nigeria · 2026" />);
    expect(getByText("Nigeria · 2026")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/components/Lower3rd.test.tsx`
Expected: FAIL ("Cannot find module './Lower3rd'").

- [ ] **Step 3: Write `connect-videos/src/components/Lower3rd.tsx`**

```tsx
import { theme } from "../theme";

export const Lower3rd: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      left: 64,
      bottom: 96,
      padding: "12px 24px",
      background: theme.colors.accent,
      color: "white",
      fontFamily: theme.fonts.sans,
      fontSize: 36,
      fontWeight: 600,
      borderRadius: theme.radii.sm,
    }}
  >
    {text}
  </div>
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/components/Lower3rd.test.tsx`
Expected: PASS (1 test).

- [ ] **Step 5: Write `connect-videos/src/components/KenBurns.tsx`**

```tsx
import { Img, useCurrentFrame, interpolate } from "remotion";

interface Props {
  src: string;
  durationFrames: number;
  zoomFrom?: number;
  zoomTo?: number;
}

export const KenBurns: React.FC<Props> = ({
  src,
  durationFrames,
  zoomFrom = 1.0,
  zoomTo = 1.08,
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, durationFrames], [zoomFrom, zoomTo], {
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale})`,
          transformOrigin: "center",
        }}
      />
    </div>
  );
};
```

- [ ] **Step 6: Write `connect-videos/src/components/CaptionBar.tsx`**

```tsx
import { theme } from "../theme";

interface Props {
  text: string;
}

export const CaptionBar: React.FC<Props> = ({ text }) => {
  if (!text) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        transform: "translateX(-50%)",
        bottom: 48,
        maxWidth: "80%",
        padding: "12px 20px",
        background: theme.colors.captionBg,
        color: theme.colors.captionFg,
        fontFamily: theme.fonts.sans,
        fontSize: 34,
        lineHeight: 1.25,
        textAlign: "center",
        borderRadius: theme.radii.sm,
      }}
    >
      {text}
    </div>
  );
};
```

- [ ] **Step 7: Run all tests to confirm none regressed**

Run: `cd connect-videos && npm test`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add connect-videos/src/components/
git commit -m "feat(videos): add Lower3rd, KenBurns, CaptionBar primitives"
```

---

### Task 6: StatCard, AppScreen, CycleStep

**Files:**
- Create: `connect-videos/src/components/StatCard.tsx`
- Create: `connect-videos/src/components/StatCard.test.tsx`
- Create: `connect-videos/src/components/AppScreen.tsx`
- Create: `connect-videos/src/components/CycleStep.tsx`

- [ ] **Step 1: Write the failing test `connect-videos/src/components/StatCard.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("renders the big number and caption", () => {
    const { getByText } = render(
      <StatCard big="29%" caption="EBF rate in Nigeria" source="NDHS 2018" />
    );
    expect(getByText("29%")).toBeTruthy();
    expect(getByText("EBF rate in Nigeria")).toBeTruthy();
    expect(getByText(/NDHS 2018/)).toBeTruthy();
  });

  it("omits the source line when not provided", () => {
    const { queryByText } = render(<StatCard big="50%" caption="x" />);
    expect(queryByText(/Source/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/components/StatCard.test.tsx`
Expected: FAIL ("Cannot find module './StatCard'").

- [ ] **Step 3: Write `connect-videos/src/components/StatCard.tsx`**

```tsx
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

interface Props {
  big: string;
  caption: string;
  source?: string;
}

export const StatCard: React.FC<Props> = ({ big, caption, source }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 12 } });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        background: theme.colors.background,
        opacity: enter,
        transform: `translateY(${(1 - enter) * 16}px)`,
        fontFamily: theme.fonts.sans,
        color: theme.colors.foreground,
      }}
    >
      <div style={{ fontSize: 280, fontWeight: 800, color: theme.colors.accent, lineHeight: 1 }}>
        {big}
      </div>
      <div style={{ fontSize: 44, maxWidth: 1200, textAlign: "center" }}>{caption}</div>
      {source && (
        <div style={{ fontSize: 24, color: theme.colors.muted }}>Source: {source}</div>
      )}
    </div>
  );
};
```

- [ ] **Step 4: Write `connect-videos/src/components/AppScreen.tsx`**

```tsx
import { Video, Img, staticFile } from "remotion";
import { theme } from "../theme";

interface Props {
  asset: string;
  caption?: string;
}

const isVideo = (s: string) => /\.(mp4|webm|mov)$/i.test(s);

export const AppScreen: React.FC<Props> = ({ asset, caption }) => {
  const src = asset.startsWith("http") ? asset : staticFile(asset);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: theme.colors.background,
        fontFamily: theme.fonts.sans,
      }}
    >
      <div
        style={{
          width: 540,
          height: 960,
          borderRadius: 56,
          background: "#000",
          padding: 16,
          boxShadow: "0 24px 64px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ width: "100%", height: "100%", borderRadius: 40, overflow: "hidden" }}>
          {isVideo(asset) ? (
            <Video src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          )}
        </div>
      </div>
      {caption && (
        <div
          style={{
            position: "absolute",
            right: 96,
            top: "50%",
            transform: "translateY(-50%)",
            maxWidth: 560,
            color: theme.colors.foreground,
            fontSize: 42,
            fontWeight: 600,
          }}
        >
          {caption}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 5: Write `connect-videos/src/components/CycleStep.tsx`**

```tsx
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

interface Props {
  label: "Learn" | "Deliver" | "Verify" | "Pay";
  index: number;
}

export const CycleStep: React.FC<Props> = ({ label, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame: frame - index * 6, fps, config: { damping: 14 } });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        opacity: enter,
        transform: `translateY(${(1 - enter) * 20}px)`,
        fontFamily: theme.fonts.sans,
        color: theme.colors.foreground,
      }}
    >
      <div
        style={{
          width: 144,
          height: 144,
          borderRadius: 9999,
          background: theme.colors.accent,
          color: "white",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 64,
          fontWeight: 700,
        }}
      >
        {index + 1}
      </div>
      <div style={{ fontSize: 38, fontWeight: 600 }}>{label}</div>
    </div>
  );
};
```

- [ ] **Step 6: Run tests to confirm**

Run: `cd connect-videos && npm test`
Expected: all tests pass (Lower3rd, StatCard, plus prior).

- [ ] **Step 7: Commit**

```bash
git add connect-videos/src/components/
git commit -m "feat(videos): add StatCard, AppScreen, CycleStep components"
```

---

### Task 7: Intro composition (15s shared)

**Files:**
- Create: `connect-videos/src/compositions/Intro.tsx`

The Intro is three beats: hook (4s) → cycle (8s, four CycleSteps) → handoff (3s).

- [ ] **Step 1: Write `connect-videos/src/compositions/Intro.tsx`**

```tsx
import { AbsoluteFill, Sequence, useVideoConfig, spring, useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { CycleStep } from "../components/CycleStep";

interface Props {
  programName: string;
  beatFrames: { hook: number; cycle: number; handoff: number };
}

const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14 } });
  return (
    <AbsoluteFill
      style={{
        background: theme.colors.background,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: theme.fonts.display,
        color: theme.colors.foreground,
        padding: 96,
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 88, fontWeight: 800, lineHeight: 1.1, opacity: enter }}>
        Pay for verified service delivery,
        <br />
        not planned activity.
      </div>
    </AbsoluteFill>
  );
};

const Cycle: React.FC = () => (
  <AbsoluteFill
    style={{
      background: theme.colors.background,
      alignItems: "center",
      justifyContent: "center",
      gap: 64,
      flexDirection: "row",
    }}
  >
    {(["Learn", "Deliver", "Verify", "Pay"] as const).map((label, i) => (
      <CycleStep key={label} label={label} index={i} />
    ))}
  </AbsoluteFill>
);

const Handoff: React.FC<{ programName: string }> = ({ programName }) => (
  <AbsoluteFill
    style={{
      background: theme.colors.background,
      alignItems: "center",
      justifyContent: "center",
      fontFamily: theme.fonts.display,
      color: theme.colors.foreground,
      padding: 96,
      textAlign: "center",
    }}
  >
    <div style={{ fontSize: 64, fontWeight: 600 }}>
      Here's how it works for
      <br />
      <span style={{ color: theme.colors.accent, fontWeight: 800 }}>{programName}</span>.
    </div>
  </AbsoluteFill>
);

export const Intro: React.FC<Props> = ({ programName, beatFrames }) => (
  <>
    <Sequence durationInFrames={beatFrames.hook}>
      <Hook />
    </Sequence>
    <Sequence from={beatFrames.hook} durationInFrames={beatFrames.cycle}>
      <Cycle />
    </Sequence>
    <Sequence from={beatFrames.hook + beatFrames.cycle} durationInFrames={beatFrames.handoff}>
      <Handoff programName={programName} />
    </Sequence>
  </>
);
```

- [ ] **Step 2: Typecheck**

Run: `cd connect-videos && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add connect-videos/src/compositions/Intro.tsx
git commit -m "feat(videos): 15s Intro composition (hook + cycle + handoff)"
```

---

### Task 8: Outro composition (8s shared)

**Files:**
- Create: `connect-videos/src/compositions/Outro.tsx`

- [ ] **Step 1: Write `connect-videos/src/compositions/Outro.tsx`**

```tsx
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

interface Props {
  programUrl: string;
}

export const Outro: React.FC<Props> = ({ programUrl }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14 } });
  return (
    <AbsoluteFill
      style={{
        background: theme.colors.foreground,
        color: "white",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
        fontFamily: theme.fonts.display,
        padding: 96,
        textAlign: "center",
        opacity: enter,
      }}
    >
      <div style={{ fontSize: 72, fontWeight: 800 }}>Connect by Dimagi</div>
      <div style={{ fontSize: 44, color: theme.colors.accent }}>
        Powering the Frontline. Paying for Results.
      </div>
      <div style={{ fontSize: 30, color: theme.colors.muted, marginTop: 24 }}>
        Become a delivery partner — {programUrl.replace(/^https?:\/\//, "")}
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 2: Typecheck and commit**

Run: `cd connect-videos && npm run typecheck`
Expected: PASS.

```bash
git add connect-videos/src/compositions/Outro.tsx
git commit -m "feat(videos): 8s Outro composition with brand close + CTA"
```

---

### Task 9: ProgramBody composition (37s, beat-dispatched)

**Files:**
- Create: `connect-videos/src/compositions/ProgramBody.tsx`

ProgramBody receives the full `ProgramSpec` plus the resolved beat frames; it dispatches each beat to the right component.

- [ ] **Step 1: Write `connect-videos/src/compositions/ProgramBody.tsx`**

```tsx
import { AbsoluteFill, Sequence, Video, Img, staticFile } from "remotion";
import { theme } from "../theme";
import { Lower3rd } from "../components/Lower3rd";
import { KenBurns } from "../components/KenBurns";
import { StatCard } from "../components/StatCard";
import { AppScreen } from "../components/AppScreen";
import type { ProgramSpec } from "../lib/spec";
import type { ResolvedBeat } from "../lib/beats";

interface Props {
  spec: ProgramSpec;
  bodyBeats: ResolvedBeat[]; // scene, problem, product, impact (order from defaults)
}

const isVideo = (s: string) => /\.(mp4|webm|mov)$/i.test(s);

const Scene: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  const clipFrames = Math.floor(durationFrames / spec.scene.clips.length);
  return (
    <AbsoluteFill style={{ background: theme.colors.foreground }}>
      {spec.scene.clips.map((clip, i) => {
        const src = clip.startsWith("http") ? clip : staticFile(clip);
        return (
          <Sequence key={i} from={i * clipFrames} durationInFrames={clipFrames}>
            {isVideo(clip) ? (
              <AbsoluteFill>
                <Video src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </AbsoluteFill>
            ) : (
              <KenBurns src={src} durationFrames={clipFrames} />
            )}
          </Sequence>
        );
      })}
      <Lower3rd text={spec.scene.lower_third} />
    </AbsoluteFill>
  );
};

const ProductBeats: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  const slot = Math.floor(durationFrames / spec.product.beats.length);
  return (
    <AbsoluteFill style={{ background: theme.colors.background }}>
      {spec.product.beats.map((b, i) => (
        <Sequence key={i} from={i * slot} durationInFrames={slot}>
          <AppScreen asset={b.asset} caption={b.caption} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

const ImpactStats: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  const slot = Math.floor(durationFrames / spec.impact.length);
  return (
    <AbsoluteFill>
      {spec.impact.map((s, i) => (
        <Sequence key={i} from={i * slot} durationInFrames={slot}>
          <StatCard big={s.big} caption={s.caption} source={s.source} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const ProgramBody: React.FC<Props> = ({ spec, bodyBeats }) => {
  const bodyStart = bodyBeats[0].startFrame;
  const renderBeat = (b: ResolvedBeat) => {
    switch (b.kind) {
      case "body_scene":
        return <Scene spec={spec} durationFrames={b.durationFrames} />;
      case "body_problem_stat":
        return (
          <StatCard
            big={spec.problem.big}
            caption={spec.problem.caption}
            source={spec.problem.source}
          />
        );
      case "body_product_beats":
        return <ProductBeats spec={spec} durationFrames={b.durationFrames} />;
      case "body_impact_stats":
        return <ImpactStats spec={spec} durationFrames={b.durationFrames} />;
      default:
        return null;
    }
  };
  return (
    <>
      {bodyBeats.map((b) => (
        <Sequence
          key={b.id}
          from={b.startFrame - bodyStart}
          durationInFrames={b.durationFrames}
        >
          {renderBeat(b)}
        </Sequence>
      ))}
    </>
  );
};
```

- [ ] **Step 2: Typecheck**

Run: `cd connect-videos && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add connect-videos/src/compositions/ProgramBody.tsx
git commit -m "feat(videos): ProgramBody composition dispatches body beats"
```

---

### Task 10: Root.tsx — wire `ProgramVideo` composition

**Files:**
- Modify: `connect-videos/src/Root.tsx`

Root reads the program slug from Remotion props at registration time, loads the YAML, resolves the timeline, and registers a single composition `ProgramVideo`. The render script will pass `--props` with the slug at render time.

- [ ] **Step 1: Rewrite `connect-videos/src/Root.tsx`**

```tsx
import { Composition, AbsoluteFill, Sequence } from "remotion";
import { loadProgramSpec, type ProgramSpec } from "./lib/spec";
import { loadDefaults, resolveBeats, type ResolvedBeat } from "./lib/beats";
import { Intro } from "./compositions/Intro";
import { ProgramBody } from "./compositions/ProgramBody";
import { Outro } from "./compositions/Outro";
import { CaptionBar } from "./components/CaptionBar";
import path from "node:path";

interface VideoProps {
  programSlug: string;
  captions?: { startFrame: number; endFrame: number; text: string }[];
}

const ProjectRoot = path.resolve(process.cwd());

const ProgramVideo: React.FC<VideoProps> = ({ programSlug, captions = [] }) => {
  const defaults = loadDefaults(path.join(ProjectRoot, "programs/_defaults.yaml"));
  const spec = loadProgramSpec(path.join(ProjectRoot, `programs/${programSlug}.yaml`));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});
  const byId = Object.fromEntries(timeline.beats.map((b) => [b.id, b])) as Record<
    string,
    ResolvedBeat
  >;
  const introBeats = {
    hook: byId.hook.durationFrames,
    cycle: byId.cycle.durationFrames,
    handoff: byId.handoff.durationFrames,
  };
  const bodyBeats = timeline.beats.filter((b) => b.kind.startsWith("body_"));
  const outroBeat = byId.cta;

  return (
    <AbsoluteFill>
      <Sequence durationInFrames={byId.handoff.startFrame + byId.handoff.durationFrames}>
        <Intro programName={spec.name} beatFrames={introBeats} />
      </Sequence>
      <Sequence
        from={bodyBeats[0].startFrame}
        durationInFrames={
          bodyBeats[bodyBeats.length - 1].startFrame +
          bodyBeats[bodyBeats.length - 1].durationFrames -
          bodyBeats[0].startFrame
        }
      >
        <ProgramBody spec={spec} bodyBeats={bodyBeats} />
      </Sequence>
      <Sequence from={outroBeat.startFrame} durationInFrames={outroBeat.durationFrames}>
        <Outro programUrl={spec.program_url} />
      </Sequence>
      {captions.map((c, i) => (
        <Sequence key={i} from={c.startFrame} durationInFrames={c.endFrame - c.startFrame}>
          <CaptionBar text={c.text} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  // Default to "mbw" so `npm start` opens with MBW preview.
  const defaultSlug = process.env.REMOTION_PROGRAM_SLUG ?? "mbw";
  const defaults = loadDefaults(path.join(ProjectRoot, "programs/_defaults.yaml"));
  const spec = loadProgramSpec(path.join(ProjectRoot, `programs/${defaultSlug}.yaml`));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});
  return (
    <Composition
      id="ProgramVideo"
      component={ProgramVideo as React.FC<Record<string, unknown>>}
      durationInFrames={timeline.totalFrames}
      fps={timeline.fps}
      width={1920}
      height={1080}
      defaultProps={{ programSlug: defaultSlug, captions: [] }}
    />
  );
};
```

- [ ] **Step 2: Typecheck**

Run: `cd connect-videos && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add connect-videos/src/Root.tsx
git commit -m "feat(videos): wire ProgramVideo composition stitching Intro+Body+Outro"
```

---

### Task 11: programs/mbw.yaml — populate from labs site

**Files:**
- Create: `connect-videos/programs/mbw.yaml`
- Create: `connect-videos/assets/programs/mbw/.gitkeep`

Data drawn from `labs.connect.dimagi.com` MBW tile and Matt's killer-demo script. Asset paths are placeholders — files will be dropped in by the user; renders against missing files will print warnings (handled in Task 13).

- [ ] **Step 1: Write `connect-videos/programs/mbw.yaml`**

```yaml
slug: mbw
name: Mother-Baby Wellness
country_focus: Nigeria
status: Piloting 2026
tagline: "Breastfeeding promotion and maternal mental health."
program_url: https://labs.connect.dimagi.com/

scene:
  clips:
    - assets/programs/mbw/drone-village.mp4
    - assets/programs/mbw/mother-baby-01.jpg
    - assets/programs/mbw/flw-home-visit.mp4
  lower_third: "Nigeria · 2026 pilot"

problem:
  big: "29%"
  caption: "exclusive breastfeeding rate in Nigeria, under 6 months"
  source: "NDHS 2018"

product:
  beats:
    - asset: assets/programs/mbw/learn-cert.mp4
      caption: "FLW certified on EBF counseling"
    - asset: assets/programs/mbw/deliver-visit.mp4
      caption: "Home visit guided, GPS-stamped"
    - asset: assets/programs/mbw/payment-notif.mp4
      caption: "Paid on verification"

impact:
  - big: "$320K"
    caption: "GiveWell pilot grant"
  - big: "2,000"
    caption: "mother–baby pairs in pilot cohort"

narration:
  generator: manual
  prompt_version: v1
  script: |
    Across Nigeria, fewer than three in ten babies are exclusively
    breastfed in their first six months — a gap with lifelong consequences.
    Connect's Mother-Baby Wellness pilot is closing that gap one home
    visit at a time. Frontline workers train and certify in our app,
    deliver visits guided step by step with GPS-stamped verification,
    and get paid the moment delivery is confirmed. The pilot, backed by
    a three-hundred-and-twenty-thousand-dollar GiveWell grant, will reach
    two thousand mother–baby pairs and lay the groundwork for national scale.

voice:
  provider: elevenlabs
  voice_id: "21m00Tcm4TlvDq8ikWAM"
  model: eleven_turbo_v2
```

- [ ] **Step 2: Create asset placeholder directory marker**

```bash
touch connect-videos/assets/programs/mbw/.gitkeep
```

- [ ] **Step 3: Validate that the spec parses**

Run: `cd connect-videos && npx tsx -e "import('./src/lib/spec.ts').then(m => console.log(m.loadProgramSpec('programs/mbw.yaml').slug))"`
Expected: prints `mbw`.

- [ ] **Step 4: Commit**

```bash
git add connect-videos/programs/mbw.yaml connect-videos/assets/programs/mbw/.gitkeep
git commit -m "feat(videos): seed MBW program YAML from labs site + Matt's script"
```

---

### Task 12: Narration module (Anthropic) and CLI

**Files:**
- Create: `connect-videos/src/lib/narration.ts`
- Create: `connect-videos/src/lib/narration.test.ts`
- Create: `connect-videos/scripts/narrate.ts`

The narration generator builds a prompt from the YAML, calls Claude, and returns a string. Tests use a mock client; the real Anthropic SDK is called only from `narrate.ts`.

- [ ] **Step 1: Write the failing test `connect-videos/src/lib/narration.test.ts`**

```ts
import { describe, it, expect, vi } from "vitest";
import { buildNarrationPrompt, generateNarration } from "./narration";
import type { ProgramSpec } from "./spec";

const sampleSpec: ProgramSpec = {
  slug: "mbw",
  name: "Mother-Baby Wellness",
  country_focus: "Nigeria",
  status: "Piloting 2026",
  tagline: "EBF and maternal mental health.",
  program_url: "https://labs.connect.dimagi.com/",
  scene: { clips: ["a.jpg"], lower_third: "Nigeria · 2026" },
  problem: { big: "29%", caption: "EBF rate", source: "NDHS 2018" },
  product: { beats: [{ asset: "x.mp4", caption: "y" }] },
  impact: [
    { big: "$320K", caption: "grant" },
    { big: "2,000", caption: "pairs" },
  ],
  narration: { generator: "anthropic", prompt_version: "v1", script: "" },
  voice: { provider: "elevenlabs", voice_id: "v", model: "eleven_turbo_v2" },
};

describe("buildNarrationPrompt", () => {
  it("embeds every quantitative claim from the spec", () => {
    const prompt = buildNarrationPrompt(sampleSpec, { wordsPerMinute: 150, durationSeconds: 45 });
    expect(prompt).toContain("29%");
    expect(prompt).toContain("$320K");
    expect(prompt).toContain("2,000");
    expect(prompt).toContain("NDHS 2018");
    expect(prompt).toContain("Mother-Baby Wellness");
  });

  it("computes a target word count from duration and WPM", () => {
    const prompt = buildNarrationPrompt(sampleSpec, { wordsPerMinute: 160, durationSeconds: 30 });
    expect(prompt).toMatch(/about 80 words/i);
  });
});

describe("generateNarration", () => {
  it("returns the model's response text", async () => {
    const fakeClient = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Generated narration." }],
        }),
      },
    };
    const out = await generateNarration(sampleSpec, {
      durationSeconds: 45,
      wordsPerMinute: 150,
      client: fakeClient as never,
    });
    expect(out).toBe("Generated narration.");
    expect(fakeClient.messages.create).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/lib/narration.test.ts`
Expected: FAIL ("Cannot find module './narration'").

- [ ] **Step 3: Write `connect-videos/src/lib/narration.ts`**

```ts
import Anthropic from "@anthropic-ai/sdk";
import type { ProgramSpec } from "./spec";

export interface NarrationOptions {
  wordsPerMinute: number;
  durationSeconds: number;
  client?: Anthropic;
}

export function buildNarrationPrompt(
  spec: ProgramSpec,
  opts: { wordsPerMinute: number; durationSeconds: number }
): string {
  const targetWords = Math.round((opts.wordsPerMinute * opts.durationSeconds) / 60);
  const productLines = spec.product.beats
    .map((b) => `  - ${b.caption}`)
    .join("\n");
  const impactLines = spec.impact
    .map((s) => `  - ${s.big} ${s.caption}`)
    .join("\n");
  return `You are writing a ~${opts.durationSeconds}-second narration script for a Connect by Dimagi program video. The narration plays over field footage, app screen recordings, and motion-graphic stat cards.

Audience: philanthropic funders and prospective local delivery organizations.
Tone: matter-of-fact, evidence-led, no marketing fluff. Verified delivery, not promises.
Length: about ${targetWords} words (at ${opts.wordsPerMinute} WPM).

PROGRAM: ${spec.name}
Country focus: ${spec.country_focus}
Status: ${spec.status}
Tagline: ${spec.tagline}

PROBLEM STAT (must appear): ${spec.problem.big} — ${spec.problem.caption}${spec.problem.source ? ` (Source: ${spec.problem.source})` : ""}

PRODUCT BEATS (in order, must be covered):
${productLines}

IMPACT STATS (must appear):
${impactLines}

Rules:
- Use only the numbers above. Do not invent quantitative claims.
- Open by setting the scene in ${spec.country_focus}.
- Touch the Connect cycle: Learn → Deliver → Verify → Pay.
- End with the impact stats.
- Output ONLY the narration text, no headings, no quotes, no stage directions.`;
}

export async function generateNarration(
  spec: ProgramSpec,
  opts: NarrationOptions
): Promise<string> {
  const client = opts.client ?? new Anthropic();
  const prompt = buildNarrationPrompt(spec, opts);
  const resp = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 800,
    messages: [{ role: "user", content: prompt }],
  });
  const text = resp.content
    .filter((c): c is { type: "text"; text: string } => c.type === "text")
    .map((c) => c.text)
    .join("\n")
    .trim();
  return text;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/lib/narration.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Write `connect-videos/scripts/narrate.ts`**

```ts
#!/usr/bin/env tsx
import { readFileSync, writeFileSync } from "node:fs";
import { parse, stringify } from "yaml";
import path from "node:path";
import { generateNarration } from "../src/lib/narration";
import { loadProgramSpec } from "../src/lib/spec";

function parseArgs(): { program: string; durationSeconds: number; dryRun: boolean } {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.split("=")[1];
  const duration = args.find((a) => a.startsWith("--duration="))?.split("=")[1];
  const dryRun = args.includes("--dry-run");
  if (!program) {
    console.error("Usage: npm run narrate -- --program=<slug> [--duration=37] [--dry-run]");
    process.exit(2);
  }
  return {
    program,
    durationSeconds: duration ? Number(duration) : 37,
    dryRun,
  };
}

async function main() {
  const { program, durationSeconds, dryRun } = parseArgs();
  const yamlPath = path.resolve("programs", `${program}.yaml`);
  const spec = loadProgramSpec(yamlPath);
  if (spec.narration.generator !== "anthropic") {
    console.error(
      `narration.generator is "${spec.narration.generator}" — refusing to overwrite. Set it to "anthropic" in ${yamlPath} first.`
    );
    process.exit(1);
  }
  console.log(`Drafting narration for ${spec.name} (${durationSeconds}s body)…`);
  const script = await generateNarration(spec, {
    wordsPerMinute: 150,
    durationSeconds,
  });
  console.log("\n--- generated narration ---\n");
  console.log(script);
  console.log("\n---------------------------\n");
  if (dryRun) return;
  const raw = readFileSync(yamlPath, "utf8");
  const obj = parse(raw);
  obj.narration.script = script;
  writeFileSync(yamlPath, stringify(obj, { lineWidth: 0 }));
  console.log(`Wrote narration.script back to ${yamlPath}.`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 6: Commit**

```bash
git add connect-videos/src/lib/narration.ts connect-videos/src/lib/narration.test.ts connect-videos/scripts/narrate.ts
git commit -m "feat(videos): Anthropic-backed narration generator with CLI"
```

---

### Task 13: Voiceover module (ElevenLabs with hash cache)

**Files:**
- Create: `connect-videos/src/lib/voiceover.ts`
- Create: `connect-videos/src/lib/voiceover.test.ts`

- [ ] **Step 1: Write the failing test `connect-videos/src/lib/voiceover.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { existsSync, rmSync, readFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { synthesize, cacheKey } from "./voiceover";

let tmpDir: string;

beforeEach(() => {
  tmpDir = path.join(os.tmpdir(), `vo-${Date.now()}-${Math.random()}`);
});

afterEach(() => {
  if (existsSync(tmpDir)) rmSync(tmpDir, { recursive: true, force: true });
});

describe("cacheKey", () => {
  it("produces stable hashes for identical inputs", () => {
    expect(cacheKey("hi", "v1", "m1")).toBe(cacheKey("hi", "v1", "m1"));
  });
  it("differs when any input changes", () => {
    expect(cacheKey("hi", "v1", "m1")).not.toBe(cacheKey("hi!", "v1", "m1"));
    expect(cacheKey("hi", "v1", "m1")).not.toBe(cacheKey("hi", "v2", "m1"));
  });
});

describe("synthesize", () => {
  it("writes audio to cache and returns its path", async () => {
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
    });
    const out = await synthesize({
      script: "hello",
      voiceId: "v1",
      model: "m1",
      cacheDir: tmpDir,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      apiKey: "test-key",
    });
    expect(existsSync(out)).toBe(true);
    expect(readFileSync(out).length).toBe(4);
    expect(fakeFetch).toHaveBeenCalledOnce();
  });

  it("returns the cached path on second call without re-fetching", async () => {
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
    });
    const args = {
      script: "hello",
      voiceId: "v1",
      model: "m1",
      cacheDir: tmpDir,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      apiKey: "test-key",
    };
    await synthesize(args);
    await synthesize(args);
    expect(fakeFetch).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/lib/voiceover.test.ts`
Expected: FAIL ("Cannot find module './voiceover'").

- [ ] **Step 3: Write `connect-videos/src/lib/voiceover.ts`**

```ts
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

export function cacheKey(script: string, voiceId: string, model: string): string {
  return createHash("sha256")
    .update(`${voiceId}::${model}::${script}`)
    .digest("hex")
    .slice(0, 16);
}

export interface SynthesizeArgs {
  script: string;
  voiceId: string;
  model: string;
  cacheDir: string;
  apiKey: string;
  fetchImpl?: typeof fetch;
}

export async function synthesize(args: SynthesizeArgs): Promise<string> {
  const { script, voiceId, model, cacheDir, apiKey } = args;
  const key = cacheKey(script, voiceId, model);
  mkdirSync(cacheDir, { recursive: true });
  const outPath = path.join(cacheDir, `${key}.mp3`);
  if (existsSync(outPath)) return outPath;
  const fetchImpl = args.fetchImpl ?? fetch;
  const resp = await fetchImpl(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
    {
      method: "POST",
      headers: {
        "xi-api-key": apiKey,
        "content-type": "application/json",
        accept: "audio/mpeg",
      },
      body: JSON.stringify({
        text: script,
        model_id: model,
        voice_settings: { stability: 0.4, similarity_boost: 0.7 },
      }),
    }
  );
  if (!resp.ok) {
    throw new Error(`ElevenLabs HTTP ${resp.status}: ${await safeText(resp)}`);
  }
  const buf = Buffer.from(await resp.arrayBuffer());
  writeFileSync(outPath, buf);
  return outPath;
}

async function safeText(r: Response): Promise<string> {
  try {
    return await r.text();
  } catch {
    return "<no body>";
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/lib/voiceover.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add connect-videos/src/lib/voiceover.ts connect-videos/src/lib/voiceover.test.ts
git commit -m "feat(videos): ElevenLabs voiceover synth with sha256 cache"
```

---

### Task 14: Captions — estimated alignment (whisper deferred)

**Files:**
- Create: `connect-videos/src/lib/captions.ts`
- Create: `connect-videos/src/lib/captions.test.ts`

Estimated alignment splits the script by sentence and distributes over the audio duration. Whisper-precision alignment is deferred (noted in spec §9).

- [ ] **Step 1: Write the failing test `connect-videos/src/lib/captions.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import { estimateCaptionTimeline } from "./captions";

describe("estimateCaptionTimeline", () => {
  it("splits a multi-sentence script into one caption per sentence", () => {
    const out = estimateCaptionTimeline({
      script: "First sentence here. Second one is longer. Third.",
      durationSeconds: 10,
      fps: 30,
      startFrame: 0,
    });
    expect(out).toHaveLength(3);
    expect(out[0].text).toBe("First sentence here.");
  });

  it("distributes durations proportional to character length", () => {
    const out = estimateCaptionTimeline({
      script: "Short. A much much much much much longer sentence here.",
      durationSeconds: 6,
      fps: 30,
      startFrame: 0,
    });
    const a = out[0].endFrame - out[0].startFrame;
    const b = out[1].endFrame - out[1].startFrame;
    expect(b).toBeGreaterThan(a);
  });

  it("ends exactly at startFrame + durationSeconds * fps", () => {
    const out = estimateCaptionTimeline({
      script: "Sentence one. Sentence two.",
      durationSeconds: 4,
      fps: 30,
      startFrame: 60,
    });
    expect(out[out.length - 1].endFrame).toBe(60 + 4 * 30);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd connect-videos && npx vitest run src/lib/captions.test.ts`
Expected: FAIL.

- [ ] **Step 3: Write `connect-videos/src/lib/captions.ts`**

```ts
export interface CaptionCue {
  startFrame: number;
  endFrame: number;
  text: string;
}

interface Args {
  script: string;
  durationSeconds: number;
  fps: number;
  startFrame: number;
}

export function estimateCaptionTimeline(args: Args): CaptionCue[] {
  const sentences = args.script
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length === 0) return [];
  const totalChars = sentences.reduce((a, s) => a + s.length, 0);
  const totalFrames = Math.round(args.durationSeconds * args.fps);
  let cursor = args.startFrame;
  const cues: CaptionCue[] = [];
  sentences.forEach((s, i) => {
    const share = s.length / totalChars;
    const dur =
      i === sentences.length - 1
        ? args.startFrame + totalFrames - cursor
        : Math.round(totalFrames * share);
    cues.push({ startFrame: cursor, endFrame: cursor + dur, text: s });
    cursor += dur;
  });
  return cues;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd connect-videos && npx vitest run src/lib/captions.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add connect-videos/src/lib/captions.ts connect-videos/src/lib/captions.test.ts
git commit -m "feat(videos): estimated caption alignment from sentence lengths"
```

---

### Task 15: Render orchestrator `scripts/render.ts`

**Files:**
- Create: `connect-videos/scripts/render.ts`

The orchestrator loads spec + defaults, synthesizes voice (skips when key absent), builds captions, then invokes Remotion's renderer programmatically.

- [ ] **Step 1: Write `connect-videos/scripts/render.ts`**

```ts
#!/usr/bin/env tsx
import { existsSync } from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { loadProgramSpec } from "../src/lib/spec";
import { loadDefaults, resolveBeats } from "../src/lib/beats";
import { synthesize } from "../src/lib/voiceover";
import { estimateCaptionTimeline } from "../src/lib/captions";

interface CliArgs {
  program: string;
  draft: boolean;
  noVoice: boolean;
  noCaptions: boolean;
}

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);
  const program = args.find((a) => a.startsWith("--program="))?.split("=")[1];
  if (!program) {
    console.error(
      "Usage: npm run render -- --program=<slug> [--draft] [--no-voice] [--no-captions]"
    );
    process.exit(2);
  }
  return {
    program,
    draft: args.includes("--draft"),
    noVoice: args.includes("--no-voice"),
    noCaptions: args.includes("--no-captions"),
  };
}

async function main() {
  const cli = parseArgs();
  const root = process.cwd();
  const defaults = loadDefaults(path.join(root, "programs/_defaults.yaml"));
  const spec = loadProgramSpec(path.join(root, `programs/${cli.program}.yaml`));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});

  if (!spec.narration.script.trim()) {
    console.error(
      `programs/${cli.program}.yaml has empty narration.script. Run "npm run narrate -- --program=${cli.program}" first, or set it manually.`
    );
    process.exit(1);
  }

  // Voiceover
  let voicePath: string | null = null;
  if (!cli.noVoice && spec.voice.provider === "elevenlabs") {
    const apiKey = process.env.ELEVENLABS_API_KEY;
    if (!apiKey) {
      console.warn(
        "ELEVENLABS_API_KEY not set; rendering silent video. Pass --no-voice to silence this warning."
      );
    } else {
      console.log("Synthesizing voiceover…");
      voicePath = await synthesize({
        script: spec.narration.script,
        voiceId: spec.voice.voice_id,
        model: spec.voice.model,
        cacheDir: path.join(root, "assets/audio"),
        apiKey,
      });
      console.log(`Voiceover ready: ${path.relative(root, voicePath)}`);
    }
  }

  // Captions over the body beats only (where narration plays).
  const bodyBeats = timeline.beats.filter((b) => b.kind.startsWith("body_"));
  const bodyStart = bodyBeats[0].startFrame;
  const bodyDuration =
    bodyBeats[bodyBeats.length - 1].startFrame +
    bodyBeats[bodyBeats.length - 1].durationFrames -
    bodyStart;
  const captions = cli.noCaptions
    ? []
    : estimateCaptionTimeline({
        script: spec.narration.script,
        durationSeconds: bodyDuration / timeline.fps,
        fps: timeline.fps,
        startFrame: bodyStart,
      });

  // Compose props for Remotion.
  const props = { programSlug: cli.program, captions };
  const propsArg = `--props=${JSON.stringify(props)}`;
  const gitSha = safeSha();
  const outName = `${spec.slug}-${cli.draft ? "draft" : "v" + gitSha}.mp4`;
  const outPath = path.join(root, "out", outName);
  const widthHeight = cli.draft ? "--width=1280 --height=720" : "";
  const crf = cli.draft ? "--crf=28" : "--crf=22";

  // Compile audio mix: if voice exists, pass it as an audio overlay starting at body.
  // For POC, render without overlaying audio in Remotion (the file is on disk for manual
  // mux); a later task can move this into a Remotion <Audio/> at body start.
  const cmd = [
    "npx remotion render src/Root.tsx ProgramVideo",
    JSON.stringify(outPath),
    propsArg,
    widthHeight,
    crf,
  ]
    .filter(Boolean)
    .join(" ");

  console.log(`Rendering → ${path.relative(root, outPath)}…`);
  execSync(cmd, { stdio: "inherit" });

  if (voicePath) {
    const muxed = outPath.replace(/\.mp4$/, "-mux.mp4");
    const voiceOffsetSeconds = bodyStart / timeline.fps;
    const ffmpegCmd = [
      "ffmpeg -y",
      `-i ${JSON.stringify(outPath)}`,
      `-itsoffset ${voiceOffsetSeconds.toFixed(3)} -i ${JSON.stringify(voicePath)}`,
      "-c:v copy -c:a aac -shortest",
      "-map 0:v:0 -map 1:a:0",
      JSON.stringify(muxed),
    ].join(" ");
    console.log(`Muxing voiceover with ffmpeg → ${path.relative(root, muxed)}…`);
    execSync(ffmpegCmd, { stdio: "inherit" });
  }

  console.log("Done.");
}

function safeSha(): string {
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return "nogit";
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 2: Typecheck**

Run: `cd connect-videos && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add connect-videos/scripts/render.ts
git commit -m "feat(videos): render orchestrator with optional VO + caption pipeline"
```

---

### Task 16: yt-dlp ingest helper

**Files:**
- Create: `connect-videos/scripts/ingest-youtube.ts`

Restricted to Dimagi-owned uploads by a `--owned` confirmation flag (enforced by convention, not crypto).

- [ ] **Step 1: Write `connect-videos/scripts/ingest-youtube.ts`**

```ts
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
  const url = args.find((a) => a.startsWith("--url="))?.split("=")[1];
  const out = args.find((a) => a.startsWith("--out="))?.split("=")[1];
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
```

- [ ] **Step 2: Commit**

```bash
git add connect-videos/scripts/ingest-youtube.ts
git commit -m "feat(videos): yt-dlp wrapper for Dimagi-owned reference ingest"
```

---

### Task 17: Brand extractor stub

**Files:**
- Create: `connect-videos/scripts/brand-extract.ts`

A minimal script that fetches the labs site HTML and prints inline CSS color tokens it finds. Manual refinement is expected; this is just a starting point.

- [ ] **Step 1: Write `connect-videos/scripts/brand-extract.ts`**

```ts
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
```

- [ ] **Step 2: Commit**

```bash
git add connect-videos/scripts/brand-extract.ts
git commit -m "feat(videos): brand-extract.ts stub to surface labs.connect colors/fonts"
```

---

### Task 18: End-to-end POC render of MBW

**Files:**
- Modify: `connect-videos/README.md` (add the smoke-test recipe)

Final task validates the pipeline end-to-end. Asset files may not all exist yet; we accept warnings/black-frame fallbacks and capture the result.

- [ ] **Step 1: Run all tests one last time**

Run: `cd connect-videos && npm test`
Expected: every test passes.

- [ ] **Step 2: Render a silent draft (no API keys needed)**

Run: `cd connect-videos && npm run render -- --program=mbw --draft --no-voice --no-captions`
Expected: produces `out/mbw-draft.mp4`. Some Img/Video tags may render as broken (missing asset files) — that's acceptable for the POC; the timeline structure is what we're validating.

- [ ] **Step 3: Inspect the output**

Run: `ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate connect-videos/out/mbw-draft.mp4`
Expected: duration ≈ 60s; resolution 1280x720 (draft) at 30fps; H.264 codec.

- [ ] **Step 4: Append a "Smoke test" section to `connect-videos/README.md`**

```markdown

## Smoke test (no API keys required)

\`\`\`
npm test
npm run render -- --program=mbw --draft --no-voice --no-captions
ffprobe connect-videos/out/mbw-draft.mp4
\`\`\`

Expected: a 60-second draft MP4 with the storyboard structure rendered.
Missing per-program asset files render as broken image/video placeholders —
drop real assets into \`assets/programs/mbw/\` to fill them in.

## Full render with voice and captions

\`\`\`
export ANTHROPIC_API_KEY=...
export ELEVENLABS_API_KEY=...
npm run narrate -- --program=mbw   # writes script back into the YAML
# Review programs/mbw.yaml narration.script, edit as desired
npm run render -- --program=mbw
\`\`\`

Output: \`out/mbw-v<sha>.mp4\` (video) and \`out/mbw-v<sha>-mux.mp4\` (with VO).
```

- [ ] **Step 5: Final commit**

```bash
git add connect-videos/README.md
git commit -m "feat(videos): end-to-end POC smoke test for MBW draft render"
```

---

## Self-review

**Spec coverage** (matched against `docs/superpowers/specs/2026-05-13-connect-program-videos-poc-design.md`):

- §3 Architecture (project layout) → Tasks 1, 5, 6, 7, 8, 9, 10
- §4 Storyboard timing as data → Task 4
- §5 ProgramSpec → Task 3
- §6 Narration pipeline (manual / anthropic / auto) → Task 12 + Task 15 (orchestrator gates on script presence)
- §7 Render pipeline → Task 15 (+ Task 18 smoke test)
- §8 POC scope → Tasks 1–18 cover the "in POC" bullets; deferred items are noted in spec §8 and not in this plan
- §9 Risks (asset gaps, license, YouTube ingest scope, caption alignment fallback) → asset gaps and license called out in Tasks 11, 18; YouTube ingest scoped via `--owned` in Task 16; caption fallback in Task 14

**Placeholder scan:** every code-touching step contains the actual code. No "TBD" / "implement later" / "similar to Task N" patterns. Commands are exact. The `assets/programs/mbw/` files referenced in `mbw.yaml` are explicitly noted as user-supplied in Tasks 11 and 18.

**Type consistency:** `ProgramSpec` (Task 3) is consumed by `resolveBeats` overrides (Task 4), `Intro` / `ProgramBody` / `Outro` props (Tasks 7–9), `Root.tsx` (Task 10), `generateNarration` (Task 12), and `render.ts` (Task 15). All names match (`beat_overrides`, `narration.script`, `voice.voice_id`, `program_url`). `ResolvedBeat` exported from `beats.ts` is imported by `ProgramBody.tsx` and `Root.tsx`.
