#!/usr/bin/env node
/**
 * Generate TypeScript types for the slice of canopy-web's API that ace-web
 * consumes, from canopy's own OpenAPI schema.
 *
 * WHY THIS EXISTS. ace-web read canopy's REST responses through hand-written
 * maps — 30 raw casts in `src/canopy/api.ts`, with manual renames
 * (`status` -> `live_status`, `last_activity_at` -> `updated_at`). canopy-web's
 * OWN frontend reads the identical endpoints through types generated from its
 * schema. So the two sides described one contract twice, and only one of them
 * was checked against the source.
 *
 * That gap has already cost a production bug: an earlier draft compared
 * `Runner.live_status` against `"ONLINE"` — the Python constant's NAME, not its
 * lowercase VALUE — which made every runner look offline and mis-fired the
 * placement banner on every chat. A generated union type makes that a compile
 * error instead of a silent behaviour change.
 *
 * WHY IT PRUNES. canopy's full schema is 208 paths / 322 schemas and generates
 * ~17,900 lines — more than twice ace-web's own generated types, for the eleven
 * operations we actually call. So `CONSUMED` below is an explicit allowlist,
 * and pruning to it keeps the committed file small enough to review.
 *
 * The allowlist is the point, not a side effect: it is the one place that
 * states, in full, what ace-web depends on from canopy. Adding a call to a new
 * canopy endpoint means adding a line here, which is exactly the moment to
 * notice you are widening the coupling.
 *
 * Usage:
 *   npm run gen:canopy-api                    # against deployed labs canopy
 *   CANOPY_SCHEMA_URL=... npm run gen:canopy-api
 *   CANOPY_SCHEMA_FILE=path npm run gen:canopy-api
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * Every canopy operation ace-web calls, as `<method> <path>`.
 *
 * Paths carry canopy's `/canopy` script-name prefix because that is how they
 * appear in the served schema (`FORCE_SCRIPT_NAME=/canopy` on labs) — and it is
 * also how ace-web reaches them, since `CanopyStatus.base_url` already includes
 * the prefix and `api.ts` appends `/api/...` to it.
 */
const CONSUMED = [
  ['get', '/canopy/api/canopy-sessions/'],
  ['get', '/canopy/api/canopy-sessions/{session_id}'],
  ['get', '/canopy/api/canopy-sessions/{session_id}/messages'],
  ['post', '/canopy/api/canopy-sessions/{session_id}/attach'],
  ['post', '/canopy/api/canopy-sessions/{session_id}/detach'],
  ['post', '/canopy/api/canopy-sessions/{session_id}/place'],
  ['put', '/canopy/api/canopy-sessions/{session_id}/page-state'],
  // The contact surface. A visitor ace-web vouches for who has no canopy
  // account is a CONTACT, and reaches these instead of the routes above —
  // same conversation, different principal, so both halves are consumed.
  ['get', '/canopy/api/contact/sessions'],
  ['get', '/canopy/api/contact/sessions/{session_id}'],
  ['get', '/canopy/api/contact/sessions/{session_id}/messages'],
  ['post', '/canopy/api/contact/sessions/{session_id}/send'],
  ['post', '/canopy/api/contact/sessions/{session_id}/attach'],
  ['post', '/canopy/api/contact/sessions/{session_id}/detach'],
  ['get', '/canopy/api/harness/runners/'],
  ['get', '/canopy/api/harness/sessions'],
  ['get', '/canopy/api/harness/turns/'],
  ['get', '/canopy/api/harness/turns/{turn_id}/events'],
]

const DEFAULT_URL = 'https://labs.connect.dimagi.com/canopy/api/openapi.json'
const OUT = new URL('../src/api/canopy-generated.ts', import.meta.url).pathname

async function loadSchema() {
  if (process.env.CANOPY_SCHEMA_FILE) {
    return JSON.parse(readFileSync(process.env.CANOPY_SCHEMA_FILE, 'utf8'))
  }
  const url = process.env.CANOPY_SCHEMA_URL || DEFAULT_URL
  const res = await fetch(url)
  if (!res.ok) throw new Error(`could not fetch canopy schema (${res.status}): ${url}`)
  return res.json()
}

/** Every `#/components/schemas/X` reachable from `roots`, transitively. */
function reachableSchemas(schema, roots) {
  const all = schema.components?.schemas ?? {}
  const keep = new Set()
  const queue = [...roots]
  while (queue.length) {
    const name = queue.pop()
    if (keep.has(name) || !(name in all)) continue
    keep.add(name)
    for (const ref of JSON.stringify(all[name]).matchAll(/#\/components\/schemas\/([A-Za-z0-9_]+)/g)) {
      queue.push(ref[1])
    }
  }
  return keep
}

const schema = await loadSchema()

const paths = {}
const roots = []
const missing = []
for (const [method, path] of CONSUMED) {
  const op = schema.paths?.[path]?.[method]
  if (!op) {
    missing.push(`${method.toUpperCase()} ${path}`)
    continue
  }
  paths[path] ??= {}
  paths[path][method] = op
  for (const ref of JSON.stringify(op).matchAll(/#\/components\/schemas\/([A-Za-z0-9_]+)/g)) {
    roots.push(ref[1])
  }
}

// An operation ace-web calls that canopy no longer serves is the single most
// important thing this script can detect, so it is fatal rather than a warning:
// a silent skip would regenerate a smaller file, `tsc` would pass, and the call
// would 404 at runtime for whoever opened the page.
if (missing.length) {
  console.error('canopy no longer serves operations ace-web calls:')
  for (const m of missing) console.error(`  ${m}`)
  console.error('\nEither canopy removed them (fix the caller) or they moved (fix CONSUMED).')
  process.exit(1)
}

const kept = reachableSchemas(schema, roots)
const pruned = {
  openapi: schema.openapi,
  info: schema.info,
  paths,
  components: {
    schemas: Object.fromEntries(
      Object.entries(schema.components.schemas).filter(([name]) => kept.has(name)),
    ),
  },
}

const dir = mkdtempSync(join(tmpdir(), 'canopy-schema-'))
const prunedPath = join(dir, 'pruned.json')
writeFileSync(prunedPath, JSON.stringify(pruned))

execFileSync(
  'npx',
  ['--yes', 'openapi-typescript@^7.13.0', prunedPath, '--output', OUT, '--immutable'],
  { stdio: 'inherit' },
)

const banner = `/**
 * GENERATED — do not edit. Run \`npm run gen:canopy-api\`.
 *
 * Types for the slice of canopy-web's API that ace-web consumes, generated from
 * canopy's own OpenAPI schema so the two cannot describe one contract twice.
 * See scripts/gen-canopy-contract.mjs for why this is pruned and what the
 * allowlist means.
 *
 * NOT ace-web's own API — that is src/api/generated.ts.
 */
`
writeFileSync(OUT, banner + readFileSync(OUT, 'utf8'))

console.log(
  `canopy contract: ${CONSUMED.length} operations, ${kept.size} schemas -> ${OUT.split('/').slice(-3).join('/')}`,
)
