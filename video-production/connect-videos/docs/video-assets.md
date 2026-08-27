# Connect video & media asset registry

Catalog of approved-for-external-use video and image assets cross-referenced
from the Connect Marketing Hub (Confluence) and the Kenya CHC media-shoot
Drive kit. Use this as the shopping list when ingesting per-program footage
via `npm run drive-fetch` (small files), `npm run ingest` (YouTube), or
manual Drive download (large files).

Authoritative source: [Connect Marketing — Confluence](https://confluence.dimagi.com/) (auth required).
External-facing tagline (per labs.connect.dimagi.com): *"Pay for verified service
delivery, not planned activity."*

## Access legend

- ✅ Accessible — directly reachable from this repo right now.
- ❌ Blocked — needs action (private video, missing share, etc.).
- ⏳ Untested.
- ⚠️ Reachable in principle but constrained (e.g. too large for MCP transport).

## Kenya CHC media-shoot kit (newly unblocked)

Drive folder: [`1AmkxI9Zoi0llDq6KzkVpnZGaCVsr0bKN`](https://drive.google.com/drive/folders/1AmkxI9Zoi0llDq6KzkVpnZGaCVsr0bKN).
Vendor: **Psych Media Productions** (Nairobi shoot, Dec 2025).
LLO: **Kikapu Garden**. Ace service account has full read access.

### Final film

| File | Drive ID | Access | Notes |
|---|---|---|---|
| `Connect by Dimagi_CHC_Long Version.mp4` | `11JyprcmSeN8Ipg9yM90tlMD8050qO3uB` | ⚠️ | Too large for `drive_download_binary` (V8 string max ~500MB cap). Download manually via the Drive web UI into `assets/ingest/chc-kit/final/` and then run `npm run map-content -- --skip-download --out=assets/ingest/chc-kit/final/`. |

### Product-feature edits (in `Video Edits/` subfolder)

All six fit in the MCP transport and are already pulled into
`assets/ingest/chc-kit/video-edits/` and staged in
`public/assets/programs/chc/`.

| Edit | Duration | Drive ID | Local path |
|---|---|---|---|
| Connect Verification Functionality | 59.4s | `1UC6QSQB2rMcDYBKcZ3Wmj-cqx7dY6Kno` | `scene-verification.mp4` |
| Connect Visit Stats 1 | 16.8s | `1aOgcC5EQioXMriZ3krVYmDTPuYrA1MT9` | `scene-stats.mp4` |
| Connect Visit Stats 2 | 8.0s | `1UlrT_yrY8tiZW4zJUI051V29gNTiWDo3` | `visit-stats.mp4` |
| GPS Capture | 13.6s | `1dvb_1TJuEfRgMr2i913h7YRSSNOXTn5f` | `scene-gps.mp4` |
| Opportunity to Learn Progression | 12.0s | `1dI_1NwTdMoW49Vk2HdJVbbni0S188H8n` | `learn-progression.mp4` |
| Payment Accrual Workflow | 9.8s | `1vyxeW7F_2vFkZukFKrMzY7caxuygDbB5` | `payment-accrual.mp4` |

Plus three review docs in the same Video Edits folder:
- `[Shared] CHC Training Video Outline` (Google Doc) — the editorial outline.
- `[Shared] Consolidated Feedback on V1 Connect CHC Video` — review notes.
- `Dimagi Feedback on Connect Video` — internal feedback.

### Raw assets (large; pull selectively)

| Folder | Drive ID | Contents | Notes |
|---|---|---|---|
| B-ROLLS | `1Gqa3emqCNbFA4VnRH5-clBReWp7JLb_I` | 96 raw MP4 clips numbered `328 0378-120` etc. | Each is a short b-roll take; pull only the ones a content-map shortlist identifies as useful. |
| INTERVIEWS | `1mBzK7HVUmSiEbhztBDyIGICg9fgPyHa8` | 15 raw interview takes | Heads-up: most will have name lower-thirds burned into the final edit but the raw takes are likely caption-free. |
| PHOTOS | `1KxS0HVE7tbqMLLv1jA6_kGd-mjggIF4T` | 84 Sony **`.ARW`** raw stills | Needs RAW→JPG conversion (`dcraw` or `darktable`) before ffmpeg can use them. Out of scope for POC. |
| SOUND | `1VJC-Z5VCyePnQrqfUhgdtSwuo2hF4ix_` | 12 `.WAV` files — speaker-named | **Real human narration source.** If we want to drop AI VO entirely, these are the lift: AMIE VACCARO, BONIFACE MUSYOKA, DIANA ACHIENG ODHIAMBO, HELLEN MAINA, MARY ATIENO, ROSEMARY KISIULA, WENDY JULIET (+ continuations) and three vaccine-administering ambient takes. WAVs at full bit depth may exceed MCP transport cap — pull individually and watch sizes. |

### Production paperwork

- `Revised Dimagi's Connect Video Project Production Quote 24 th Nov 2025.pdf`
  (`1vfbzhMoEm91zE0GBv3jgBNRr9Skin4Jx`) — Vendor quote/SoW. Reference only.

## Other marketing-hub videos

| Asset | URL / ID | Access | Notes |
|---|---|---|---|
| Connect Demo: Pay for Outcomes, Not Effort (Aug 2025) | YouTube `VRbvUj9LTUg` | ✅ | 4:30. Generic product demo; FLW journey end-to-end. Mapped in `assets/ingest/mbw-ref/`. |
| Mwasuze Mutya — Kateregga Bazilio (PIPNU) | YouTube `o1nHOWhInbY` | ✅ but mostly unusable | 49:39 Luganda. TV station bug burned into every frame. |
| Inside the Child Health Campaign in Kenya | YouTube `oiUuT5v6ir0` | ❌ Private | Likely a public-facing cut of the Long Version film above. Same content; switch privacy if you want a YouTube-embeddable version. |

## Other Drive surfaces

| ID | Role | Access | Notes |
|---|---|---|---|
| `1bPVNwiIGZQ8APgCJKS8AJe1iaQ7qM3x7` | Public Documents folder | ✅ | 1-pager PDF, learning agenda, intervention briefs, KMC overview doc. No video. |
| `16peiK_R_hk2CxKyG0B2L6XrcytRQGDcV` | (unknown — was thought to be the CHC kit before this one) | ❌ | Empty listing. Possibly a stale/private folder. |
| `1SPIlRavu1wqyHcliK4OLFTWzDm7m-5hU` | (unknown) | ❌ | Same. |
| `1MLGVhiA0YCt_NpjuF4Gveu1s3kwygD7-`, `1cy8n364Uo-…`, `1sp6SCC34Lh…`, `1FOxnhX9V…` | individual files | ⏳ | Not probed. Probably the AI Supervision Demo, AI Microplan Execution, etc. videos from the marketing hub. |
| 6 `docs.google.com/presentation/d/…` decks | Source decks | ⏳ | Connect Source Deck, 2023 in Review, Overview, ECD, CHC, KMC. |

## How to fetch new Drive assets

For files small enough to fit through the MCP transport (~9 MB MP4 limit
in practice, plus base64 overhead):

```
# From the assistant context, call drive_download_binary(<fileId>). The
# transport saves the JSON to a tool-results path. Then decode:

npm run drive-fetch -- --in=<tool-result.txt> --out=assets/ingest/<kit>/<name>.mp4
```

For larger files, use the Drive web UI manually. Drop the file under
`assets/ingest/<kit>/` (the directory is gitignored) and proceed.

## Working with a new video

```
# Optional: download with content-map automation
npm run map-content -- "--url=<youtube_url>" --out=assets/ingest/<slug>-ref/ --owned

# Slice clean segments using timestamps from the contact-sheet
SRC=assets/ingest/<slug>-ref/<video_id>.mkv
OUT=public/assets/programs/<slug>
ffmpeg -y -ss <start> -i "$SRC" -t <duration> -c:v libx264 -preset fast -an "$OUT/<role>.mp4"
```

## Brand voice / messaging quick reference

- **Hero (per labs.connect.dimagi.com):** "Pay for verified service delivery,
  not planned activity."
- **Outro tagline (per marketing hub):** "Connect: Powering the Frontline.
  Paying for Results."
- **Elevator pitch:** "Connect is building a new model for global
  development—one that directly links funding to verified service delivery
  at the frontline, enabling more transparency, accountability, and impact."
- **Frontline Worker** and **LLO** (Locally-Led Organization) are the
  preferred capitalized forms.
- "Connect platform" is preferred over "our app".

When marketing-hub copy conflicts with labs.connect.dimagi.com:
**the website wins** — it's actively maintained.
