import { createHash } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { probeDurationSeconds } from "./probe";

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
  const mp3Path = path.join(cacheDir, `${key}.mp3`);
  const jsonPath = path.join(cacheDir, `${key}.json`);
  if (existsSync(mp3Path) && existsSync(jsonPath)) return mp3Path;

  if (!existsSync(mp3Path)) {
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
          // Softer, more documentary-style delivery: higher stability for
          // calmer pacing, lower similarity_boost for a more natural read,
          // small style nudge away from a flat baseline.
          voice_settings: {
            stability: 0.6,
            similarity_boost: 0.45,
            style: 0.2,
            use_speaker_boost: true,
          },
        }),
      }
    );
    if (!resp.ok) {
      throw new Error(`ElevenLabs HTTP ${resp.status}: ${await safeText(resp)}`);
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    writeFileSync(mp3Path, buf);
  }

  // Always (re)write the sidecar when missing — covers (a) brand-new
  // synthesis and (b) pre-sidecar mp3s left over from an earlier render.
  writeFileSync(
    jsonPath,
    JSON.stringify(
      {
        voice_id: voiceId,
        model,
        text: script,
        duration_sec: probeDurationSeconds(mp3Path),
        generated_at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  return mp3Path;
}

async function safeText(r: Response): Promise<string> {
  try {
    return await r.text();
  } catch {
    return "<no body>";
  }
}

export interface PerBeatNarration {
  beatId: string;
  text: string;
  audioPath: string;
}

/**
 * Synthesize one audio file per beat-with-text. Each call goes through
 * the same cache-key hash so identical text returns instantly. Skips
 * beats with empty text. Returns the entries in input order so the
 * mux step can iterate alongside resolved beat start times.
 */
export async function synthesizePerBeat(args: {
  byBeat: Record<string, string>;
  voiceId: string;
  model: string;
  cacheDir: string;
  apiKey: string;
  fetchImpl?: typeof fetch;
}): Promise<PerBeatNarration[]> {
  const out: PerBeatNarration[] = [];
  for (const [beatId, rawText] of Object.entries(args.byBeat)) {
    const text = rawText.trim();
    if (!text) continue;
    let audioPath: string;
    try {
      audioPath = await synthesize({
        script: text,
        voiceId: args.voiceId,
        model: args.model,
        cacheDir: args.cacheDir,
        apiKey: args.apiKey,
        fetchImpl: args.fetchImpl,
      });
    } catch (e) {
      // Wrap to include which beat blew up. Without this, a 401 from
      // ElevenLabs surfaces as `ElevenLabs HTTP 401: ...` with no
      // hint that the failure came from the hook beat vs the impact
      // beat vs etc. — and the caller has to grep the spec to figure
      // out which text triggered it. Surface the beat id + first 80
      // chars of the text so debugging is one read away.
      const preview = text.length > 80 ? text.slice(0, 80) + "…" : text;
      const message = e instanceof Error ? e.message : String(e);
      throw new Error(
        `Voiceover synthesis failed for beat '${beatId}' ("${preview}"): ${message}`
      );
    }
    out.push({ beatId, text, audioPath });
  }
  return out;
}
