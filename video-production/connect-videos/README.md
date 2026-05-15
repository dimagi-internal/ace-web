# connect-videos

Template-driven 60-second videos for Connect programs on labs.connect.dimagi.com.

## Setup

```
npm install
```

## Commands

- `npm start` — open Remotion Studio for live preview
- `npm run narrate -- --program=mbw` — draft narration via Anthropic into the YAML
- `npm run render -- --program=mbw` — full pipeline → out/mbw-v<sha>.mp4
- `npm test` — run unit tests

See `docs/superpowers/specs/2026-05-13-connect-program-videos-poc-design.md` for the design.

## Smoke test (no API keys required)

```
npm test
npm run render -- --program=mbw --draft --no-voice --no-captions
ffprobe connect-videos/out/mbw-draft.mp4
```

Expected: a 60-second draft MP4 with the storyboard structure rendered.
Missing per-program asset files render as broken image/video placeholders —
drop real assets into `assets/programs/mbw/` to fill them in.

## Full render with voice and captions

```
export ANTHROPIC_API_KEY=...
export ELEVENLABS_API_KEY=...
npm run narrate -- --program=mbw   # writes script back into the YAML
# Review programs/mbw.yaml narration.script, edit as desired
npm run render -- --program=mbw
```

Output: `out/mbw-v<sha>.mp4` (video) and `out/mbw-v<sha>-mux.mp4` (with VO).
