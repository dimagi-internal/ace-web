import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
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

/**
 * Per-character alignment timings returned by ElevenLabs'
 * /with-timestamps endpoint. `characters[i]` is the literal character,
 * `*_seconds[i]` is when it starts/ends within the synthesized clip.
 * Used to compute exact moments for "learn"/"deliver"/"verify"/"paid"
 * so the cycle highlight transitions on the spoken word rather than
 * on a proportional word-index estimate.
 */
export interface Alignment {
  characters: string[];
  character_start_times_seconds: number[];
  character_end_times_seconds: number[];
}

/**
 * Find the start time (in seconds, relative to the clip) where `word`
 * first appears in the alignment. Case-insensitive prefix match: passing
 * "verif" matches both "verify" and "verified"; "paid" matches "paid"
 * but not "pay". Returns `null` if the word never appears.
 *
 * Implementation: rebuild the synthesized string from `characters[]`,
 * find the word boundary index, look up its start_seconds.
 */
export function wordStartSeconds(
  alignment: Alignment, wordStem: string,
): number | null {
  const stem = wordStem.toLowerCase();
  const text = alignment.characters.join("").toLowerCase();
  // Match word boundary: preceded by non-letter (or start of string)
  // and starts with the stem.
  const re = new RegExp(`(^|[^a-z])${stem}`);
  const m = text.match(re);
  if (!m || m.index === undefined) return null;
  const idx = m.index + (m[1] ? m[1].length : 0);
  if (idx < 0 || idx >= alignment.character_start_times_seconds.length) {
    return null;
  }
  return alignment.character_start_times_seconds[idx];
}

/**
 * Read the alignment sidecar for an already-synthesized clip. Returns
 * `null` if the file is missing or was written before the timestamps
 * endpoint switch (legacy sidecars don't carry `alignment`).
 */
export function readAlignment(jsonPath: string): Alignment | null {
  try {
    const raw = JSON.parse(readFileSync(jsonPath, "utf8"));
    if (raw && Array.isArray(raw.alignment?.characters)) {
      return raw.alignment as Alignment;
    }
  } catch {
    // fall through
  }
  return null;
}

export async function synthesize(args: SynthesizeArgs): Promise<string> {
  const { script, voiceId, model, cacheDir, apiKey } = args;
  const key = cacheKey(script, voiceId, model);
  mkdirSync(cacheDir, { recursive: true });
  const mp3Path = path.join(cacheDir, `${key}.mp3`);
  const jsonPath = path.join(cacheDir, `${key}.json`);

  // Cache hit only when BOTH mp3 and sidecar with alignment exist —
  // if the sidecar predates the alignment switch we re-synth so the
  // cycle's word-timing path can drive off real character timings.
  if (existsSync(mp3Path) && existsSync(jsonPath)) {
    const cached = readAlignment(jsonPath);
    if (cached) return mp3Path;
  }

  let alignment: Alignment | null = null;

  const fetchImpl = args.fetchImpl ?? fetch;
  // /with-timestamps returns base64-encoded mp3 + per-character timing.
  // Both arrive in one call so the audio bytes and the alignment can't
  // disagree (which they would if we synthesized once for the mp3 and
  // re-synthesized later just for timings — ElevenLabs samples a fresh
  // delivery each time even with stability tuned high).
  const resp = await fetchImpl(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/with-timestamps`,
    {
      method: "POST",
      headers: {
        "xi-api-key": apiKey,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        text: script,
        model_id: model,
        voice_settings: {
          stability: 0.6,
          similarity_boost: 0.45,
          style: 0.2,
          use_speaker_boost: true,
        },
      }),
    },
  );
  if (!resp.ok) {
    throw new Error(`ElevenLabs HTTP ${resp.status}: ${await safeText(resp)}`);
  }
  const payload = (await resp.json()) as {
    audio_base64?: string;
    alignment?: Alignment;
  };
  if (!payload.audio_base64) {
    throw new Error("ElevenLabs response missing audio_base64");
  }
  const buf = Buffer.from(payload.audio_base64, "base64");
  writeFileSync(mp3Path, buf);
  alignment = payload.alignment ?? null;

  // Write the sidecar with alignment data. Legacy fields (voice_id,
  // model, text, duration_sec, generated_at) stay so the audio library
  // sync still parses them.
  writeFileSync(
    jsonPath,
    JSON.stringify(
      {
        voice_id: voiceId,
        model,
        text: script,
        duration_sec: probeDurationSeconds(mp3Path),
        generated_at: new Date().toISOString(),
        alignment,
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
