interface McpToolDefinition {
  name: string;
  description: string;
  /** Human-facing one-liner (fleet #1967). Optional; consumers fall back to
   *  description. Kept in step with shared/src/types.ts — scripts/lib/
   *  check-inlined-types.mjs reports drift at publish time. */
  summary?: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, unknown>;
    required?: string[];
    anyOf?: Array<{ required: string[] }>;
    oneOf?: Array<{ required: string[] }>;
    allOf?: Array<{ required: string[] }>;
  };
  outputSchema?: Record<string, unknown>;
}

interface McpToolExport {
  tools: McpToolDefinition[];
  callTool: (name: string, args: Record<string, unknown>) => Promise<unknown>;
  meter?: { credits: number };
  cost?: Record<string, unknown>;
  provider?: string;
}

/**
 * Was this failure OUR OWN web service? — the other half of `internal-db-class.ts`.
 *
 * fleet #1089 pulled failures from our own Postgres out of `upstream_down` by
 * keying on the SQLSTATE inside PostgREST's four-key error envelope. That
 * covered the majority and structurally could not cover the rest: the rest
 * never reach Postgres, so they carry no SQLSTATE. What was left, measured over
 * the 24h to 2026-09-02T15:00Z (fleet #1096):
 *
 *     5  pipeworx-catalog  get_pack_tools     Pipeworx catalog error: 522 — error code: 522
 *     3  fleet             fleet_list_open …  upstream_down: Fleet task queue did not respond within 25s
 *
 * 521/522/523/526 are Cloudflare saying its edge could not reach an ORIGIN, and
 * in both of those rows the origin is ours — `gateway.pipeworx.io` for the
 * catalog pack (it self-fetches when the gateway hasn't injected a manifest),
 * our own Supabase for fleet. There is no third party anywhere in either call.
 * Same defect as #1089: our own outage filed under `upstream_down`, the one
 * class that means "the source is unreachable and there is nothing for us to
 * fix", which is why the problem-tools triage skips it.
 *
 * WHY NOT A WORDING RULE. The obvious fix is to match `fleet db error:` and
 * `Pipeworx catalog error:` in classifyToolError. Each is emitted from exactly
 * one site today, so it would work today. It would also rot the first time
 * somebody rewords a label — silently, and in the direction of hiding our own
 * outage, which is worse than the bug being fixed. Every prose rule in
 * error-class.ts has needed widening as packs invented new wording (#409/#450/
 * #584); that history is most of that file's comment budget.
 *
 * WHAT THIS KEYS ON INSTEAD: **the host the call actually reached.** A URL's
 * hostname is a fact about the call, not a guess about its prose. Two
 * consequences that a pack-level flag could not give us, and the reason the
 * flag was rejected:
 *
 *   - It describes the CALL, not the pack. `govcon-intel` fans out to our own
 *     Supabase AND to genuine third parties; `court-listener` holds our cache
 *     in Supabase and fetches courtlistener.com. An `internallyHosted: true` on
 *     either pack would relabel a real third-party outage as ours — inventing
 *     work, which is the same class of error in the opposite direction.
 *   - It covers every future internal pack for free, instead of one declared
 *     slug at a time.
 *
 * WHY IT SURVIVES A REWORD. The marker below is not matched as a literal by two
 * separate files. `markInternalOrigin()` writes it and `internalHostMetricsClass()`
 * reads it, both from the single exported `INTERNAL_ORIGIN_MARKER` constant in
 * this module — so changing the wording changes both sides in the same edit and
 * cannot desynchronise them. The pack's own label (`fleet db error:`,
 * `Pipeworx catalog error:`) is not read at all: reword it freely, the class is
 * unaffected. That is the property `stripClassPrefix` lacked when it drifted
 * from its own classifier three times and needed a CI gate to hold them
 * together.
 *
 * WHERE THE 5xx TEST LIVES. `markInternalOrigin` is called from the places that
 * hold the real `Response` — `httpError`/`httpErrorMessage` and the timeout
 * branch of `fetchWithTimeout` in `shared/src/http.ts` — so "is this an
 * availability failure" is decided from the actual status code, never re-derived
 * by scraping a number out of a sentence. A 404 from our own registry for a slug
 * that does not exist is a caller's bad argument and is deliberately NOT marked.
 */

/**
 * OUR OWN web service was unreachable — not an upstream, and never `upstream_down`.
 *
 * ONE value, not three, unlike `internal_db_*`. That split existed because a
 * slow query, an exhausted pool and an unknown SQLSTATE have different owners
 * and different fixes. Here there is only one story to tell — an origin we run
 * did not answer the edge — and one owner. A bucket with no distinct owner per
 * value is decoration; #724 is what happens when a class holds several
 * situations, and inventing sub-values ahead of a reason to act on them
 * differently is the same mistake with the sign flipped.
 *
 * METRICS ONLY, exactly like PLATFORM_KEY_ERROR_CLASS and the internal_db
 * values. `classifyToolError` still answers `upstream_down` for the retry and
 * hint paths, which only care whether retrying or a sibling tool might work —
 * and it might. Nothing a caller sees or is charged changes here.
 *
 * READ SIDE: this value is in BROKEN_TOOL_CLASSES, FAULT_CLASSES and
 * ALL_ERROR_CLASSES in `workers/registry-api/src/index.ts`. All three, or it
 * lands on no dashboard — fleet #721 is the warning, where the #719 split
 * worked on the write side and was invisible for weeks.
 */
const INTERNAL_SERVICE_UNREACHABLE_CLASS = 'internal_service_unreachable';

/**
 * The token that carries "this origin is ours" from the call site to the
 * classifier.
 *
 * Appended to the error message rather than attached to the Error object,
 * because the object does not survive the trip: 275 packs return `{ error:
 * string }` instead of throwing, the gateway reads `observedError` as a string,
 * and the fleet pack rebuilds its error from a captured status + body across a
 * retry loop. A property on an Error would be dropped by every one of those
 * paths and the class would work in tests and vanish in production.
 *
 * WORDING IS LOAD-BEARING, same rule as labelAge's note in authority.ts. This
 * string is appended to a pack's thrown Error message (shared/src/http.ts),
 * and a thrown Error's message is exactly what the gateway hands back to the
 * caller as `content[0].text` when nothing rewrites it (workers/gateway/src
 * catches the throw and sets `rawResult.message = stripClassPrefix(error)`,
 * which does not touch this suffix) — so the original wording,
 * " [pipeworx-hosted origin — our own service, not a third party]", was not a
 * theoretical leak: it shipped live on pipeworx-catalog's 522s, 7 times in 6
 * hours on 2026-09-02 (see tests/golden-internal-service.test.ts), verbatim
 * naming Pipeworx as the host. check:hosting-claims never caught it because it
 * did not scan shared/ at all (task #2009). Reworded to describe the
 * OBSERVATION (the origin did not answer) without a claim about who runs it —
 * the identical fix labelAge got: drop the possessive, keep the fact.
 */
const INTERNAL_ORIGIN_MARKER = ' [origin did not respond — retry before concluding the named source is down]';

/**
 * Supabase's data plane for a project is `<ref>.supabase.co`, where the ref is
 * exactly twenty lowercase letters (ours is `pqauisounztsgdgfkhke`).
 *
 * Matching the shape rather than listing the ref keeps this correct when we add
 * a project — `supabaseEnv` on a pack entry already points some packs at a
 * second one — while still excluding `status.supabase.co`, which is Supabase's
 * own status page and emphatically not our database. Verified 2026-09-02 by
 * `grep -rhoE '[a-z0-9-]+\.supabase\.(co|in)' mcps shared workers scripts`: the
 * only real project ref anywhere in the tree is ours, the rest are doc
 * placeholders (`abc`, `xyz`, `example`) which this pattern also excludes. Same
 * finding internal-db-class.ts relies on for the PostgREST envelope being ours
 * by construction.
 */
const SUPABASE_PROJECT_HOST = /^[a-z]{20}\.supabase\.(co|in)$/;

/**
 * Is this a host WE run?
 *
 * Deliberately NOT including `*.workers.dev`: plenty of third-party APIs are
 * hosted on workers.dev, so the suffix says where something runs and not who
 * owns it. Every internal call we actually make goes to a `pipeworx.io`
 * hostname or to our Supabase project, both of which are ownership facts.
 *
 * `workers/gateway/src/provenance.ts`'s `OUR_HOSTS` answers the same
 * question and DOES include `workers.dev` — a documented divergence
 * (task #2051), not a bug to converge. That list decides what a response may
 * cite as a data SOURCE, where a false negative (citing our own worker as an
 * external source) is the hosting-disclosure leak this whole file exists to
 * prevent, so it errs broad. This one decides who gets BLAMED for a 5xx in
 * outage metrics read by on-call, where a false positive (crediting our own
 * infra with a third party's outage) hides the real failure, so it errs
 * narrow. Same suffix, opposite direction, because they are never called for
 * the same reason.
 *
 * Returns false on anything unparseable rather than throwing — this runs inside
 * an error path, and an error path that can itself throw turns a diagnosable
 * failure into a mystery.
 */
function isPipeworxOrigin(url: string | URL | undefined | null): boolean {
  if (!url) return false;
  let host: string;
  try {
    host = new URL(url instanceof URL ? url.href : url).hostname.toLowerCase();
  } catch {
    return false;
  }
  if (host === 'pipeworx.io' || host.endsWith('.pipeworx.io')) return true;
  return SUPABASE_PROJECT_HOST.test(host);
}

/**
 * Append the marker when this failure was OUR origin failing to answer.
 *
 * `status` is the HTTP status when there is one, and omitted for a timeout —
 * where there is no response at all, and "the origin did not answer" is the
 * whole observation. Statuses below 500 are left alone: a 404 from our own
 * registry for a slug that does not exist is the caller's argument, not our
 * outage, and marking it would put ordinary 404s on the incident dashboard.
 *
 * Idempotent, so a message that is wrapped and re-marked on the way up (the
 * fleet pack's retry loop re-throws through two layers) carries the marker once.
 */
function markInternalOrigin(
  message: string,
  url: string | URL | undefined | null,
  status?: number,
): string {
  if (status !== undefined && status < 500) return message;
  if (!isPipeworxOrigin(url)) return message;
  if (message.includes(INTERNAL_ORIGIN_MARKER)) return message;
  return message + INTERNAL_ORIGIN_MARKER;
}

/**
 * Which blob4 value a failure from our own web services books as, or undefined
 * if this is not one.
 *
 * Ordered AFTER `internalDbMetricsClass` at the call site: a PostgREST envelope
 * from our own Supabase is a strictly more specific statement about the same
 * row (which of our services, and why), and the two cannot disagree about
 * whether the failure is ours.
 */
function internalHostMetricsClass(error: string): string | undefined {
  return error.includes(INTERNAL_ORIGIN_MARKER) ? INTERNAL_SERVICE_UNREACHABLE_CLASS : undefined;
}


/**
 * One place to turn a failed `fetch` into an error a caller can act on.
 *
 * Nearly every pack was written the same way:
 *
 *     if (!res.ok) throw new Error(`Unsplash: ${res.status}`);
 *
 * which discards the response body — and the body is usually where the upstream
 * says what was actually wrong ("**symbol** not found: GBP", "parameter `year`
 * out of range", "unknown taxonomy id"). The caller gets a number, cannot
 * self-correct, and retries the same broken call. A 2026-07-31 sweep found this
 * shape in 481 of 1,400 packs, 47 of them PLATFORM-keyed.
 *
 * It also hides bugs one level down. Two of the first three packs audited had a
 * second defect that only existed because of this line: unsplash's rate-limit
 * branch sat BELOW a catch-all and was unreachable, and bea-gov parsed
 * `BEAAPI.Error.APIErrorDescription` below a `!res.ok` throw that made the
 * parsing dead code for every non-200.
 *
 * DELIBERATELY NOT A CLASSIFIER. It does not add `user_error:` /
 * `upstream_down:` prefixes. Those decide which tier a failure lands in, and the
 * `error` tier is what the daily problem-tools list is built from — it means
 * "Pipeworx has a defect". A 400 is genuinely ambiguous: often a caller's bad
 * argument, but sometimes a query WE built wrong (ted-eu comma-joined its CPV
 * values into something TED rejected, and that bug was found only because it sat
 * in `error`). Blanket-classifying 400s as caller mistakes would have hidden it.
 * A pack that KNOWS which it is should keep saying so explicitly; this helper is
 * for the 481 that say nothing at all.
 */

/** Longest upstream explanation we'll pass through. Enough for a real message,
 *  short enough that an HTML page or a stack trace can't swamp the error. */

const MAX_DETAIL = 300;

/**
 * Default bound for `fetchWithTimeout` when a pack doesn't state its own.
 *
 * 25s mirrors the number `epo-ops` landed on after measuring the real failure:
 * a degraded upstream that doesn't error, it just never answers, and a Worker
 * sits in `await fetch()` until ITS OWN execution budget kills the request —
 * which can take minutes, not seconds (epo_ops_search_patents measured 4-8
 * MINUTE hangs before this existed). 25s is short enough that a caller gets a
 * fast, actionable error instead of holding the connection, and long enough
 * that it doesn't false-trip on a merely-slow-but-alive upstream.
 */
const DEFAULT_FETCH_TIMEOUT_MS = 25_000;

/**
 * Read the body of a failed response and fold it into a throwable Error.
 *
 * Usage — note the `await`, which is the one thing that makes this a mechanical
 * change rather than a drop-in:
 *
 *     if (!res.ok) throw await httpError(res, 'Unsplash');
 *
 * Safe to call on any non-ok response: a body that is missing, empty, unreadable
 * or HTML degrades to exactly the old `Name: 404` string rather than throwing
 * something new from inside the error path.
 */
async function httpError(res: Response, name: string): Promise<Error> {
  return new Error(await httpErrorMessage(res, name));
}

/** The message text without constructing an Error — for packs that need to wrap
 *  it in their own envelope or add an explicit classification prefix. */
async function httpErrorMessage(res: Response, name: string): Promise<string> {
  // The one place a 5xx from a host WE run gets stamped as ours. `res.url` is
  // the URL the fetch actually resolved to (after redirects), so this is a fact
  // about the call rather than a guess from the `name` the pack passed in —
  // reword that label freely, the class does not move. See
  // internal-host-class.ts; no-op for every third-party upstream, which is why
  // this touches 481 packs' error text and changes none of it.
  return markInternalOrigin(
    `${name}: ${res.status}${detailSuffix(await readDetail(res))}`,
    res.url,
    res.status,
  );
}

/**
 * Just the upstream's own explanation — no name, no status.
 *
 * For a pack that has already said both in its own sentence. epo-ops reads
 * `EPO rejected this search as too large (HTTP 413) — ${httpErrorMessage(…)}`,
 * which rendered as `… (HTTP 413) — EPO: 413.` once the XML detail was being
 * dropped: the upstream named twice, the status twice, and the one thing EPO
 * actually said ("Not enough characters before truncation character") nowhere
 * (fleet #712). Returns '' when the body carries nothing readable, so a caller
 * can fall back to its own wording.
 */
async function upstreamDetail(res: Response): Promise<string> {
  return readDetail(res);
}

/**
 * Read a SUCCESSFUL response as JSON, failing loudly when it isn't JSON.
 *
 * `httpError` above only ever runs on `!res.ok`, which leaves the nastier half
 * of the problem unhandled: an upstream that answers **HTTP 200 with an HTML
 * page**. A bot wall, a login redirect, a maintenance interstitial and a CDN
 * error page are all 200s, so `res.ok` is true, and `res.json()` then throws
 * `Unexpected token '<', "<!DOCTYPE "... is not valid JSON`.
 *
 * That string is the problem. It names no upstream, carries no status, and
 * reads like a parser bug in Pipeworx — so it lands in the `error` tier, which
 * means "we have a defect", and the caller is told nothing they can act on.
 * data.govt.nz sat dead behind an Imperva challenge this way and every
 * status-code health check we own reported it green (7889a845). A zero-length
 * body has the same shape: `Unexpected end of JSON input`, seen this week on
 * uk-gazette (83% of external calls) and census.
 *
 * UNLIKE `httpError`, this one DOES classify, and the asymmetry is deliberate.
 * A 400 is genuinely ambiguous — often the caller's bad argument, sometimes a
 * query we built wrong — so blanket-classifying it would hide our own bugs.
 * There is no such ambiguity here: **no argument a caller can pass makes a JSON
 * API return an HTML page.** It is always the upstream, so `upstream_down:` is
 * a statement of fact rather than a guess, and it keeps these out of the
 * problem-tools list where they crowd out real defects.
 *
 *     const data = await parseJson<Feed>(res, 'UK Gazette');
 *
 * Call it only after the `!res.ok` check — on a failed response you want
 * `httpError`, which mines the body for the upstream's own explanation.
 */
async function parseJson<T>(res: Response, name: string): Promise<T> {
  let raw: string;
  try {
    raw = await res.text();
  } catch {
    throw new Error(
      `upstream_down: ${name} returned a body that could not be read (HTTP ${res.status}). ` +
        'The connection most likely dropped mid-response; retrying is reasonable.',
    );
  }

  const type = res.headers.get('content-type') ?? 'no content-type';

  if (!raw.trim()) {
    throw new Error(
      `upstream_down: ${name} answered HTTP ${res.status} with an EMPTY body where JSON was expected (${type}). ` +
        'Nothing about the request can cause this — it is an upstream fault, and the same call may well work on retry.',
    );
  }

  // Checked before parsing rather than in the catch, because knowing it is
  // markup is what turns "we failed to parse something" into "they served a
  // web page" — the second is diagnosable, the first is not.
  const head = raw.slice(0, 200).trimStart().toLowerCase();
  if (head.startsWith('<!doctype') || head.startsWith('<html') || head.startsWith('<?xml')) {
    const kind = head.startsWith('<?xml') ? 'an XML document' : 'an HTML page';
    // The summary, not the source. Pasting the first 120 characters of a web
    // page handed the agent `<!DOCTYPE html><html lang="en"…` — the same leak
    // this branch exists to describe (fleet #712).
    throw new Error(
      `upstream_down: ${name} answered HTTP ${res.status} with ${kind} instead of JSON (${type}). ` +
        'That is typically a bot wall, a login redirect or a maintenance page — it is returned as a SUCCESS, ' +
        `so status-code health checks read it as fine. No argument change will get past it. ` +
        `The page says: ${summarizeErrorBody(raw) || 'nothing readable'}`,
    );
  }

  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error(
      `upstream_down: ${name} answered HTTP ${res.status} with a body that is not valid JSON (${type}). ` +
        `It begins: ${stripMarkup(raw).slice(0, 120) || '(unreadable)'}`,
    );
  }
}

/**
 * `fetch`, but bounded — the fix for a systemic gap found 2026-08-30: a grep
 * audit of every pack's `mcps/*\/src/index.ts` found 1,339 of ~1,500 call
 * `fetch()` with NO timeout guard anywhere in the file. Two of those
 * (epo-ops, statcan) were confirmed live-hanging for 4-8 minutes before this
 * existed — every unguarded call carries the same risk, just unconfirmed.
 *
 * Mirrors the `epoFetch` wrapper `mcps/epo-ops/src/index.ts` shipped first:
 * bound the request with `AbortSignal.timeout`, and on a timeout/abort throw
 * an `upstream_down:` error that names the upstream and the bound rather than
 * letting the raw `TimeoutError`/`AbortError` (which names neither) propagate.
 * `upstream_down:` is deliberate, same reasoning as `parseJson` above — no
 * argument a caller passes can make an upstream hang, so it is always the
 * upstream's fault, and marking it that way keeps a slow API off the
 * problem-tools list where it would crowd out our own defects.
 *
 * Usage — a mechanical swap for a bare `fetch(url, init)`:
 *
 *     const res = await fetchWithTimeout(url, init, 'Some API');
 *
 * Pass `timeoutMs` as a fourth argument to override the default for a pack
 * with a known-slower upstream; the label should be the same short name you'd
 * pass to `httpError`/`httpErrorMessage` for that call.
 */
async function fetchWithTimeout(
  url: string | URL,
  init: RequestInit = {},
  name: string,
  timeoutMs: number = DEFAULT_FETCH_TIMEOUT_MS,
): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    if (err instanceof Error && (err.name === 'TimeoutError' || err.name === 'AbortError')) {
      // States the OBSERVATION (no response in N seconds), not a diagnosis.
      // "appears to be degraded" is an inference about the vendor that we have
      // not checked, and it is wrong in a way that misdirects whoever reads it:
      // a timeout from a Worker can equally mean OUR egress is blocked.
      //
      // Measured today (2026-09-01, fleet #1047): every call to
      // mainnet.base.org failed from the x402 facilitator while the identical
      // request from a laptop returned 200. Base was entirely healthy; the
      // public RPC refuses Cloudflare Worker egress. Had this message fired
      // there it would have blamed Base by name, and the next person would have
      // waited for a vendor outage to clear that did not exist.
      // A timeout has no status to test — there is no response at all — so
      // `markInternalOrigin` is called without one: an origin we run that never
      // answered is an availability failure by definition. This is the half of
      // fleet #1096 with neither a SQLSTATE nor a status code to key on.
      throw new Error(
        markInternalOrigin(
          `upstream_down: ${name} did not respond within ${timeoutMs / 1000}s. ` +
            `That can be ${name} being slow or down, or this environment being unable to reach it ` +
            `(some hosts refuse datacenter/Worker egress) — retry shortly, and check reachability ` +
            `from elsewhere before concluding ${name} is down.`,
          url,
        ),
      );
    }
    // Fleet #2382. Everything that isn't a timeout/abort here is a genuine
    // NETWORK-LEVEL failure — DNS resolution, connection refused, TLS handshake,
    // Cloudflare's own "Network connection lost." — meaning `fetch()` itself
    // threw and no HTTP response of any kind was ever received. Until this fix
    // that raw exception was rethrown VERBATIM: a bare `TypeError: fetch failed`
    // (or the Workers-runtime equivalent) names no upstream, carries no class
    // token, and reads exactly like a defect in OUR code — because it says
    // nothing about the call at all. It landed in `error`, the tier that means
    // "Pipeworx has a defect", for every one of the (at the time of writing)
    // ~470 packs that call this helper directly with no wrapper of their own.
    //
    // `dexscreener` hit this independently (fleet #1579) and fixed it with a
    // bespoke per-pack try/catch around `fetchWithTimeout`. That fix is correct
    // but only covers one pack; every other caller of this shared helper still
    // leaked the raw exception. Moving the same fix HERE — the one place that
    // already carries the timeout case — covers every pack that uses
    // `fetchWithTimeout` without a wrapper, for free, and without widening
    // `classifyToolError`'s regex list: the fix is giving the message a proper
    // `upstream_down:` token at the point the two facts (no response was ever
    // received, and which host we were trying to reach) are actually in hand,
    // not teaching the classifier to guess from prose after the fact.
    //
    // Safe on the same grounds as the timeout branch above: no argument a
    // caller passes can make `fetch()` itself throw a connection-level error,
    // so this is always an availability failure, never a caller mistake. Same
    // `markInternalOrigin` treatment — an origin we run that never answered is
    // still ours, not a third party's outage.
    const raw = err instanceof Error ? err.message : String(err);
    throw new Error(
      markInternalOrigin(
        `upstream_down: could not reach ${name} at all (${raw.slice(0, 160)}). ` +
          `No request reached ${name}, so this says NOTHING about whether the arguments you passed ` +
          'are valid — do not re-check them on the strength of this error. Retry shortly.',
        url,
      ),
    );
  }
}

function detailSuffix(detail: string): string {
  return detail ? ` — ${detail}` : '';
}

async function readDetail(res: Response): Promise<string> {
  let raw: string;
  try {
    raw = await res.text();
  } catch {
    // Body already consumed, or the connection died mid-read. The status alone
    // is still worth throwing — never let the error path throw its own error.
    return '';
  }
  return summarizeErrorBody(raw);
}

/**
 * Turn ANY error body — JSON, HTML, XML or plain text — into one short phrase
 * that never contains markup.
 *
 * This used to just drop an HTML or XML body on the floor, on the reasoning
 * that markup crowds out the status. That was half right. Dropping it loses the
 * one sentence a caller could have acted on: an `Access Denied` title, an SDMX
 * `<message:Error>` text, an OPS fault string. A 2026-08-30 support sweep
 * measured 13 of 291 caller-facing error rows carrying a raw page or document
 * verbatim, across 11 packs, and in every one of them the useful content —
 * "Access Denied", "Invalid country code", "SCRAPE_TIMEOUT" — was in there,
 * buried in markup the agent had to parse out of a string (fleet #712).
 *
 * So: extract the meaning, discard the markup. The output is passed through
 * `stripMarkup` unconditionally, which is what lets `check:error-body-leak`
 * assert mechanically that no caller-facing message can contain `<?xml`,
 * `<!DOCTYPE` or `<html`.
 */
function summarizeErrorBody(raw: string): string {
  if (!raw || !raw.trim()) return '';

  const head = raw.slice(0, 400).trimStart().toLowerCase();

  // An HTML error page (Cloudflare interstitial, nginx default, a login
  // redirect) says what it is in its <title>, and almost nowhere else.
  if (head.startsWith('<!doctype') || head.startsWith('<html')) {
    const title = htmlTitle(raw);
    return title
      ? `${title} (upstream returned an HTML error page, not an API response)`
      : 'upstream returned an HTML error page, not an API response';
  }

  // XML fault documents — EPO OPS, SDMX (`<message:Error>`), SOAP faults. The
  // human sentence sits in a child element whose tag name says what it is.
  if (head.startsWith('<?xml') || head.startsWith('<')) {
    const fault = xmlFaultText(raw);
    return fault
      ? `${stripMarkup(fault).slice(0, MAX_DETAIL)} (from the upstream's XML error document)`
      : 'upstream returned an XML error document with no readable message';
  }

  // Most JSON error bodies bury one human sentence among ids and echoed request
  // params. Prefer that sentence; fall back to the whole body when the shape is
  // unfamiliar, since an unfamiliar shape is exactly when we can least afford to
  // guess wrong and show nothing.
  const fromJson = messageFromJson(raw);
  return stripMarkup(fromJson ?? raw).slice(0, MAX_DETAIL);
}

/** The `<title>` of an HTML error page, or its first `<h1>` — the two places a
 *  bot wall, a 502 and an "Access Denied" all state what happened. */
function htmlTitle(raw: string): string | null {
  const head = raw.slice(0, 4000);
  for (const re of [/<title[^>]*>([\s\S]*?)<\/title>/i, /<h1[^>]*>([\s\S]*?)<\/h1>/i]) {
    const m = re.exec(head);
    const text = m ? stripMarkup(m[1]) : '';
    if (text) return text.slice(0, 160);
  }
  return null;
}

/** Tag names that carry the explanation in an XML fault document, namespace
 *  prefix optional (`<message:Error>`, `<com:Text>`, `<faultstring>`). */
const XML_FAULT_TAG_RE =
  /<(?:[A-Za-z0-9_.-]+:)?(?:text|message|description|faultstring|reason|detail|title|errormessage|error)\b[^>]*>([^<]{2,400})</i;

function xmlFaultText(raw: string): string | null {
  const head = raw.slice(0, 8000);
  const tagged = XML_FAULT_TAG_RE.exec(head);
  if (tagged && tagged[1].trim()) return tagged[1];

  // Nothing conventionally named — take the longest text node instead. A fault
  // document with one sentence in an oddly named element is still readable;
  // returning nothing at all is not.
  let best = '';
  for (const m of head.matchAll(/>([^<>]{8,400})</g)) {
    const text = m[1].trim();
    if (text.length > best.length) best = text;
  }
  return best || null;
}

/**
 * Remove every tag and stray angle bracket, then collapse whitespace.
 *
 * Applied to everything on the way out, including the JSON and plain-text
 * paths, because an upstream is free to embed markup in a JSON string field —
 * and a leak is a leak regardless of which branch produced it.
 */
function stripMarkup(s: string): string {
  return collapse(decodeEntities(s.replace(/<[^>]*>/g, ' ')).replace(/[<>]/g, ' '));
}

/** The handful of entities that show up in error-page titles. Decoded AFTER
 *  tags are stripped and BEFORE the angle-bracket sweep, so `&lt;script&gt;`
 *  in a title cannot decode into markup that survives — EMBL-EBI's ChEMBL 500
 *  page renders as `500 Internal Server Error &lt; EMBL-EBI` otherwise. */
function decodeEntities(s: string): string {
  return s
    .replace(/&(?:amp|#0*38);/gi, '&')
    .replace(/&(?:lt|#0*60);/gi, '<')
    .replace(/&(?:gt|#0*62);/gi, '>')
    .replace(/&(?:quot|#0*34);/gi, '"')
    .replace(/&(?:#0*39|apos|#x0*27);/gi, "'")
    .replace(/&nbsp;/gi, ' ');
}

/** The conventional "what went wrong" field, under any of the names upstreams
 *  actually use. Checked in order; first non-empty string wins. */
const MESSAGE_KEYS = [
  'message', 'error_message', 'errorMessage', 'detail', 'details',
  'description', 'error_description', 'reason', 'title', 'fault',
];

function messageFromJson(raw: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return pickMessage(parsed, 0);
}

function pickMessage(node: unknown, depth: number): string | null {
  // Two levels covers `{error: {message}}` and `{errors: [{detail}]}`, the two
  // shapes that account for nearly all of them, without walking a large payload.
  if (depth > 2 || node == null) return null;

  if (typeof node === 'string') return node.trim() || null;

  if (Array.isArray(node)) {
    for (const item of node) {
      const found = pickMessage(item, depth + 1);
      if (found) return found;
    }
    return null;
  }

  if (typeof node !== 'object') return null;
  const obj = node as Record<string, unknown>;

  for (const key of MESSAGE_KEYS) {
    const v = obj[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  // `{error: …}` where error is itself an object or a string — the single most
  // common wrapper, so it is worth descending into by name rather than scanning
  // every key and risking picking up an echoed request parameter.
  for (const key of ['error', 'errors', 'fault', 'Error', 'data']) {
    if (key in obj) {
      const found = pickMessage(obj[key], depth + 1);
      if (found) return found;
    }
  }
  return null;
}

/** Errors are read in a single line of log output; newlines and runs of
 *  whitespace make a multi-line body unreadable there. */
function collapse(s: string): string {
  return s.replace(/\s+/g, ' ').trim();
}
/**
 * BIS MCP — Bank for International Settlements statistics (no auth)
 *
 * The "central banks' central bank" publishes data on cross-border banking,
 * FX, debt securities, monetary policy rates, payment systems, and credit.
 * SDMX 2.1 REST endpoint, free, no key.
 *
 * API: https://stats.bis.org/api-doc/v2/
 * Tools:
 * - list_curated_flows: pre-vetted dataflow refs by topic
 * - search_dataflows:   keyword search across the BIS dataflow registry
 * - fetch_dataset:      tidy rows for one dataflow (CSV-with-labels under the hood)
 * - bis_credit_gap:     credit-to-GDP ratio / trend / gap for one country
 */


// Bound the fetch() calls in this pack that pass no signal of their own — a
// file with one guarded call still reads as "guarded" to the file-level grep
// while its other call sites hang unbounded (fleet #685).
async function pwFetch(url: string | URL, init?: RequestInit): Promise<Response> {
  return fetchWithTimeout(url, init ?? {}, 'BIS');
}

const BASE_URL = 'https://stats.bis.org/api/v2';

interface CuratedFlow {
  flow_ref: string;
  topic: string;
  title: string;
}

// Every ref below was checked against BIS's live dataflow registry on 2026-07-29
// (structure/dataflow/BIS/*/*) and fetched successfully. Six of the previous
// entries were NOT in that registry at all -- BIS folded the separate daily
// flows into their parent (WS_CBPOL_D -> WS_CBPOL, WS_EER_D -> WS_EER,
// WS_XRU_D -> WS_XRU), retired WS_FAS and WS_LONG_PP, and moved WS_TC to
// version 2.0. So this "pre-vetted" list was handing callers dead refs, which
// then surfaced as a bare "BIS returned no data" -- reading as our bug on a
// flow_ref we ourselves recommended. WS_TC was also listed twice AND mislabeled
// as the Triennial Central Bank Survey; the flow is Total credit.
// If a fetch of one of these ever returns no data, re-check the registry before
// assuming the caller's key is wrong.
const CURATED: CuratedFlow[] = [
  { flow_ref: 'BIS,WS_CBPOL,1.0', topic: 'rates', title: 'Central bank policy rates (daily + monthly)' },
  { flow_ref: 'BIS,WS_CBTA,1.0', topic: 'rates', title: 'Central bank total assets' },
  { flow_ref: 'BIS,WS_EER,1.0', topic: 'fx', title: 'Effective exchange rates' },
  { flow_ref: 'BIS,WS_XRU,1.0', topic: 'fx', title: 'US-dollar exchange rates' },
  { flow_ref: 'BIS,WS_LBS_D_PUB,1.0', topic: 'banking', title: 'Locational banking statistics (LBS)' },
  { flow_ref: 'BIS,WS_CBS_PUB,1.0', topic: 'banking', title: 'Consolidated banking statistics (CBS)' },
  { flow_ref: 'BIS,WS_DEBT_SEC2_PUB,1.0', topic: 'debt', title: 'International debt securities' },
  { flow_ref: 'BIS,WS_TC,2.0', topic: 'credit', title: 'Total credit (to non-financial sectors)' },
  { flow_ref: 'BIS,WS_GLI,1.0', topic: 'credit', title: 'Global liquidity indicators' },
  { flow_ref: 'BIS,WS_CREDIT_GAP,1.0', topic: 'credit', title: 'Credit-to-GDP gaps' },
  { flow_ref: 'BIS,WS_DSR,1.0', topic: 'credit', title: 'Debt service ratios' },
  { flow_ref: 'BIS,WS_OTC_DERIV2,1.0', topic: 'derivatives', title: 'OTC derivatives outstanding' },
  { flow_ref: 'BIS,WS_XTD_DERIV,1.0', topic: 'derivatives', title: 'Exchange-traded derivatives' },
  { flow_ref: 'BIS,WS_CPP,1.0', topic: 'property', title: 'Commercial property prices' },
  { flow_ref: 'BIS,WS_SPP,1.0', topic: 'property', title: 'Selected residential property prices' },
  { flow_ref: 'BIS,WS_DPP,1.0', topic: 'property', title: 'Detailed residential property prices' },
  { flow_ref: 'BIS,WS_LONG_CPI,1.0', topic: 'prices', title: 'Consumer prices (long series)' },
];

const tools: McpToolExport['tools'] = [
  {
    name: 'list_curated_flows',
    description:
      'List BIS dataflow refs we have pre-vetted, grouped by topic (rates, fx, banking, debt, credit, property, derivatives, finance). Use the flow_ref with fetch_dataset. For everything else use search_dataflows or browse https://stats.bis.org.',
    inputSchema: {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Optional topic filter' },
      },
      required: [],
    },
  },
  {
    name: 'search_dataflows',
    description:
      'Search the BIS SDMX dataflow registry by keyword against dataflow name and ID. Returns matched flow_refs (e.g., \'BIS,WS_CBPOL_D,1.0\') ready to pass to fetch_dataset, capped at limit (default 25, max 100).',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Keyword (matches dataflow name)' },
        limit: { type: 'number', description: 'Max results (default 25, max 100)' },
      },
      required: ['query'],
    },
  },
  {
    name: 'fetch_dataset',
    description:
      'Fetch tidy rows from a BIS dataflow. flow_ref is "BIS,<id>,<version>" and the VERSION IS NOT ALWAYS 1.0 — "BIS,WS_CBPOL,1.0" (central bank policy rates), "BIS,WS_XRU,1.0" (US-dollar exchange rates), but "BIS,WS_TC,2.0" (total credit). BIS re-versions flows in place, so a guessed version returns no data rather than an error; take the exact ref from list_curated_flows or search_dataflows instead of assuming one. The key string is a dot-separated dimension filter (e.g., "D.US" — frequency.country). ALWAYS pass start_period / end_period ("2020", "2020-Q1", "2020-01"): the big banking and debt flows are multi-megabyte and an unbounded request can time out.',
    inputSchema: {
      type: 'object',
      properties: {
        flow_ref: { type: 'string', description: 'SDMX dataflow reference' },
        key: { type: 'string', description: 'Dot-separated dimension key (empty for all)' },
        start_period: { type: 'string', description: 'Inclusive start' },
        end_period: { type: 'string', description: 'Inclusive end' },
        limit: { type: 'number', description: 'Cap rows (default 5000)' },
      },
      required: ['flow_ref'],
    },
  },
  {
    // Named for what a practitioner asks for, because that is the only way the
    // router can find it. The question "what is the latest credit-to-GDP gap
    // for the United States" used to land on fetch_dataset, which then had to
    // be handed a flow_ref, a five-part positional key, AND the knowledge that
    // the gap is CG_DTYPE "C" -- three guesses, and it got all three wrong
    // (fleet #468: it guessed the total-credit flow with a two-part key). The
    // data was always there; nothing pointed at it.
    name: 'bis_credit_gap',
    description:
      'Credit-to-GDP gap for one country from the BIS early-warning indicators: the credit-to-GDP ratio, its long-run one-sided HP-filter trend, and the gap between them in percentage points of GDP. The gap is the Basel III common reference point for setting the countercyclical capital buffer and a standard banking-crisis early-warning signal, so a large positive gap means private non-financial credit is running above its long-run trend and a negative gap means it is running below. Quarterly, 44 economies plus the euro area aggregate, history back to the 1960s for the longest series. Accepts a country name or an ISO alpha-2 code.',
    inputSchema: {
      type: 'object',
      properties: {
        country: {
          type: 'string',
          description: 'Country name or ISO alpha-2 code, e.g. "United States" or "US". "Euro area" returns the XM aggregate.',
        },
        start_period: { type: 'string', description: 'Inclusive start, e.g. "2020" or "2020-Q1"' },
        end_period: { type: 'string', description: 'Inclusive end, e.g. "2025-Q4"' },
        limit: { type: 'number', description: 'Max quarters returned, most recent first (default 20)' },
      },
      required: ['country'],
    },
  },
];

async function callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  switch (name) {
    case 'list_curated_flows':
      return listCurated(args.topic as string | undefined);
    case 'search_dataflows':
      return searchDataflows(reqStr(args, 'query', '"policy rates"'), (args.limit as number) ?? 25);
    case 'fetch_dataset':
      return fetchDataset(
        reqStr(args, 'flow_ref', '"BIS,WS_CBPOL_D,1.0"'),
        (args.key as string | undefined) ?? '',
        args.start_period as string | undefined,
        args.end_period as string | undefined,
        (args.limit as number) ?? 5000,
      );
    case 'bis_credit_gap':
      return creditGap(
        reqStr(args, 'country', '"United States"'),
        args.start_period as string | undefined,
        args.end_period as string | undefined,
        (args.limit as number) ?? 20,
      );
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function reqStr(args: Record<string, unknown>, key: string, example: string): string {
  const v = args[key];
  if (typeof v !== 'string' || !v.trim()) {
    throw new Error(`Required argument "${key}" is missing or empty. Pass a string like ${example}.`);
  }
  return v;
}

function listCurated(topic?: string) {
  const filtered = topic ? CURATED.filter((f) => f.topic === topic) : CURATED;
  return {
    count: filtered.length,
    topics: Array.from(new Set(CURATED.map((f) => f.topic))).sort(),
    flows: filtered,
    note: 'For full catalog: https://stats.bis.org or search_dataflows.',
  };
}

async function searchDataflows(query: string, limit: number) {
  const res = await pwFetch(`${BASE_URL}/structure/dataflow/BIS/all/latest?detail=allstubs`, {
    // v2 rejects the v1 media-type version with 406 Not Acceptable — and because
    // classifyToolError reads a bare 4xx as a throttle, that 406 was logging as
    // "BIS is rate-limiting us" rather than "we asked wrong". 2.0.0 is required.
    headers: { Accept: 'application/vnd.sdmx.structure+json;version=2.0.0' },
  });
  if (!res.ok) {
    throw await httpError(res, 'BIS dataflow registry error');
  }
  const data = (await parseJson<unknown>(res, 'BIS')) as {
    data?: {
      dataflows?: { id?: string; agencyID?: string; version?: string; name?: string; names?: Record<string, string> }[];
    };
  };
  const flows = data.data?.dataflows ?? [];
  const q = query.toLowerCase();
  const matched = flows.filter((f) => {
    const name = (f.name ?? f.names?.en ?? '').toLowerCase();
    return name.includes(q) || (f.id ?? '').toLowerCase().includes(q);
  });
  const capped = matched.slice(0, Math.min(100, Math.max(1, limit)));
  return {
    total_matched: matched.length,
    returned: capped.length,
    dataflows: capped.map((f) => ({
      flow_ref: `${f.agencyID ?? 'BIS'},${f.id ?? ''},${f.version ?? '1.0'}`,
      id: f.id ?? null,
      version: f.version ?? null,
      name: f.name ?? f.names?.en ?? null,
    })),
  };
}

/**
 * Ask for CSV that says what its own codes mean.
 *
 * Every call this pack made requested the SDMX v1 format token
 * `csvfilewithlabels`. BIS v2 does not reject it -- it ignores it and answers
 * 200 with plain coded CSV, so the request looked like it worked and the rows
 * came back as bare dimension codes: `CG_DTYPE "C"`, `UNIT_MEASURE "770"`,
 * `BORROWERS_CTY "US"`. Nothing in such a row says which series it is. That is
 * how fleet #468 presented -- a caller asked for the US credit-to-GDP gap, the
 * numbers were in the response, and the answer came back "the tool returned no
 * usable data", because -11.5378 next to the letter "C" is not an answer to
 * anything. The failure was silent in both directions: no error from BIS, and
 * no missing rows for us to notice.
 *
 * The v2 spelling is a separate `labels` parameter. Verified live 2026-08-20
 * against WS_CREDIT_GAP, WS_TC, WS_DSR and WS_CBPOL: identical rows, plus a
 * name column after each coded one ("C" -> "Credit-to-GDP gaps (actual-trend)",
 * "770" -> "Percentage of GDP"). The defect was never specific to the credit
 * gap -- it was every row of every BIS flow we have ever returned.
 */
function setCsvFormat(url: URL): void {
  url.searchParams.set('format', 'csv');
  url.searchParams.set('labels', 'both');
}

const SDMX_ID = /^[A-Z][A-Z0-9_]*$/;

/**
 * `labels=both` interleaves a human name column after each coded column
 * (FREQ, Frequency, BORROWERS_CTY, Borrowers' country, ...). Fold each pair
 * into `<ID>` plus `<ID>_label`, so a row carries both the code you filter on
 * and the words that say what it is.
 *
 * Uncoded columns (TIME_PERIOD, OBS_VALUE, COMPILATION, TITLE) have no name
 * column and pass through untouched. They are told apart by the header itself:
 * an SDMX id is upper-snake and a display name never is, so a header cell
 * following an id and not shaped like one is that id's label.
 */
function planColumns(header: string[]): { names: string[]; from: number[] } {
  const names: string[] = [];
  const from: number[] = [];
  for (let i = 0; i < header.length; i++) {
    const h = header[i] ?? '';
    names.push(h);
    from.push(i);
    const next = header[i + 1];
    if (next !== undefined && SDMX_ID.test(h) && !SDMX_ID.test(next)) {
      names.push(`${h}_label`);
      from.push(i + 1);
      i++;
    }
  }
  return { names, from };
}

/**
 * Build the v2 data URL. BIS runs SDMX v2, which differs from v1 in two ways
 * this pack got wrong on every single call — 14 registered failures in the week
 * of 2026-07-29, a 100% failure rate across both tools:
 *
 *  1. The flow reference is THREE PATH SEGMENTS, not one comma-joined,
 *     URL-encoded segment. `BIS%2CWS_CBPOL%2C1.0` 404s; `BIS/WS_CBPOL/1.0` works.
 *  2. The key `all` is a v1 idiom and is REJECTED by v2 — it must be omitted (or
 *     `*`). `/1.0/all` answers 404 "No results for query", which reads like an
 *     empty dataset rather than a malformed request, so the bug looked like
 *     missing data for a year rather than a broken URL.
 *
 * Verified 2026-07-29 against WS_CBPOL: the corrected shape returns 46KB of CSV
 * where every previous shape 404'd.
 */
function buildDataUrl(flowRef: string, key: string): URL {
  // Accept both our curated "BIS,WS_CBPOL,1.0" form and a slash-separated one.
  const parts = flowRef.split(/[,/]/).map((p) => p.trim()).filter(Boolean);
  const [agency, id, version] =
    parts.length >= 3 ? parts : ['BIS', parts[0] ?? '', parts[1] ?? '1.0'];
  const k = key.trim();
  // Empty and "all" both mean "every series"; v2 spells that as an omitted key.
  // The key itself is a dot-separated dimension filter (`D.US`) and may carry
  // `+` for OR, so it is deliberately not URL-encoded.
  const keyPath = !k || k.toLowerCase() === 'all' ? '' : `/${k}`;
  return new URL(
    `${BASE_URL}/data/dataflow/${encodeURIComponent(agency)}/${encodeURIComponent(id)}/${encodeURIComponent(version)}${keyPath}`,
  );
}

/**
 * Turn "BIS returned no data" into a statement of WHICH cause, not a list of
 * candidates.
 *
 * The old message named both possibilities — wrong flow_ref, or an over-filtered
 * key — and left the caller to work out which. That is not a cosmetic problem.
 * BIS re-versions flows IN PLACE (WS_TC is version 2.0; the daily flows folded
 * into their parents), and the version is part of the ref, so a stale ref
 * returns no data rather than an error. A caller reading "or the dimension key
 * filtered everything out" reasonably concludes the key is wrong and walks
 * permutations of it forever, because no key will ever work against a version
 * that does not exist. That is the shape of the live defect this fixes: one
 * registered caller failing ~20x on WS_TC,1.0 — a flow whose only version is
 * 2.0 — while the message pointed them at their key.
 *
 * These cases are distinguishable, so distinguish them. The comment on CURATED
 * already says to "re-check the registry before assuming the caller's key is
 * wrong"; this does that automatically instead of asking a human to remember.
 *
 * Runs only on the 404 path, and never throws: a diagnosis that fails falls
 * back to the original both-causes text, which is strictly what we had before.
 */
async function flowVersionsFor(id: string): Promise<string[]> {
  const res = await pwFetch(`${BASE_URL}/structure/dataflow/BIS/all/latest?detail=allstubs`, {
    headers: { Accept: 'application/vnd.sdmx.structure+json;version=2.0.0' },
  });
  if (!res.ok) return [];
  const data = (await res.json()) as {
    data?: { dataflows?: { id?: string; version?: string }[] };
  };
  const want = id.toLowerCase();
  return (data.data?.dataflows ?? [])
    .filter((f) => (f.id ?? '').toLowerCase() === want)
    .map((f) => f.version ?? '')
    .filter(Boolean);
}

// Bounded fetch for the diagnostic path: a probe that hangs is worse than one
// that fails, since it delays turning a 404 into an answer. Any abort/timeout
// is caught by diagnoseNoData's own try/catch and falls back to `generic`.
async function fetchBounded(url: string, ms = 8000, init?: RequestInit): Promise<Response> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

// Cap on how much CSV we materialize. The exact repro of fleet #449 — WS_CBPOL
// key "D.DE" with no period bound — is a 13.9MB BIS response, and parseCsv
// builds every row BEFORE the row `limit` applies, so the worker died on memory
// as a Cloudflare 1102: no data, no message, strictly worse than the bad
// message the task started from. We only ever return `limit` rows, so bytes
// past this cap could only feed rows we were going to drop anyway.
const MAX_CSV_BYTES = 6 * 1024 * 1024;

async function readCapped(res: Response, cap: number): Promise<{ text: string; exceeded: boolean }> {
  const body = res.body;
  if (!body) return { text: await res.text(), exceeded: false };
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let text = '';
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    text += decoder.decode(value, { stream: true });
    if (bytes > cap) {
      await reader.cancel().catch(() => {});
      return { text, exceeded: true };
    }
  }
  return { text: text + decoder.decode(), exceeded: false };
}

async function diagnoseNoData(
  flowRef: string,
  key: string,
  start?: string,
  end?: string,
): Promise<string> {
  const generic =
    `BIS returned no data for flow_ref "${flowRef}"${key.trim() ? ` with key "${key}"` : ''}. ` +
    `Either the flow_ref is wrong — get a valid one from search_dataflows or list_curated_flows — ` +
    `or the dimension key filtered everything out. Keys are dot-separated and positional ` +
    `(e.g. "D.US" is frequency.country); omit key entirely to fetch the whole flow.`;

  try {
    const parts = flowRef.split(/[,/]/).map((p) => p.trim()).filter(Boolean);
    const [, id, version] =
      parts.length >= 3 ? parts : ['BIS', parts[0] ?? '', parts[1] ?? '1.0'];
    if (!id) return generic;

    // 1. Version check. Curated table first (free, and it is the list we tell
    //    callers to trust), then the live registry for everything else.
    const curated = CURATED.find(
      (f) => f.flow_ref.split(',')[1]?.toLowerCase() === id.toLowerCase(),
    );
    const curatedVersion = curated?.flow_ref.split(',')[2];
    const known = curatedVersion ? [curatedVersion] : await flowVersionsFor(id);

    if (known.length && !known.includes(version)) {
      return (
        `BIS has no flow "${id}" at version ${version} — it is version ${known.join(' / ')}. ` +
        `Retry with flow_ref "BIS,${id},${known[0]}". BIS re-versions flows in place and the ` +
        `version is part of the ref, so a stale version returns no data rather than an error. ` +
        `Your dimension key${key.trim() ? ` "${key}"` : ''} is not the problem here.`
      );
    }
    if (!known.length && !curated) {
      return (
        `BIS has no dataflow with id "${id}". Get a valid flow_ref from list_curated_flows ` +
        `(pre-vetted) or search_dataflows (full registry).`
      );
    }

    // 2. The ref is good — ask BIS directly whether this EXACT key has ever
    //    matched a real series, independent of the caller's period.
    //
    //    The previous version of this check only ran "when the caller already
    //    bounded the period" (to dodge an expensive unbounded fetch) — but the
    //    live failing account (fleet #449, 2026-08) never sent start/end, so
    //    that branch never fired and every one of its 22 failures got the
    //    `generic` text above with no diagnosis at all. That is the actual bug:
    //    not that the message was wrong, but that it was unreachable for the
    //    caller who needed it most.
    //
    //    `detail=serieskeysonly` scoped to the caller's OWN key is cheap
    //    regardless of flow size or history length, because BIS filters
    //    server-side before returning anything — verified live: a 50-year
    //    daily series (BIS,WS_CBPOL,1.0 key D.DE) returns in <1s / <100 bytes
    //    key-scoped, vs 13.9MB/30s for the SAME key with full observations and
    //    no period bound, vs 12MB/25s+ timeout for `serieskeysonly` on the
    //    whole flow with no key at all. Scoping by key, not by period, is what
    //    keeps this affordable — so this now runs unconditionally.
    if (key.trim()) {
      const keyProbe = buildDataUrl(flowRef, key);
      setCsvFormat(keyProbe);
      keyProbe.searchParams.set('detail', 'serieskeysonly');
      const keyRes = await fetchBounded(keyProbe.toString());
      let keyMatched = false;
      if (keyRes.ok) {
        // A capped-out read means the key matched MANY series — valid a fortiori.
        const capped = await readCapped(keyRes, 512 * 1024);
        keyMatched = capped.exceeded || parseCsv(capped.text).length > 1;
      }

      if (keyMatched) {
        // The key is real. BIS has published under it at some point — find
        // the most recent observation and surface BIS's own explanation if it
        // gives one. This is the case this fix exists for: WS_CBPOL key
        // "D.DE" is genuinely valid (Germany had its own policy rate through
        // 1998-12-31) but BIS's own COMPILATION text says outright "the
        // series is discontinued as Germany joined the euro area" — DE, FR,
        // BE, AT all discontinued the same way and now report under the
        // euro-area aggregate "XM". A caller filtering for a recent period
        // gets zero rows for reasons that have nothing to do with the key
        // being malformed.
        const lastProbe = buildDataUrl(flowRef, key);
        setCsvFormat(lastProbe);
        lastProbe.searchParams.set('lastNObservations', '1');
        let lastPeriod = '';
        let note = '';
        try {
          const lastRes = await fetchBounded(lastProbe.toString());
          if (lastRes.ok) {
            // lastNObservations=1 is one row per matched series; a broad key can
            // still match thousands, so cap — we only read the first data row.
            const rows = parseCsv((await readCapped(lastRes, 512 * 1024)).text);
            if (rows.length > 1) {
              const hdr = rows[0] ?? [];
              const row = rows[1] ?? [];
              const col = (name: string) => {
                const i = hdr.indexOf(name);
                return i >= 0 ? (row[i] ?? '') : '';
              };
              lastPeriod = col('TIME_PERIOD');
              const explain = [col('COMPILATION'), col('SUPP_INFO_BREAKS')]
                .filter(Boolean)
                .join(' ')
                .trim();
              if (explain) {
                note = ` BIS's own note on this series: "${explain.slice(0, 320)}${explain.length > 320 ? '…' : ''}"`;
              }
            }
          }
        } catch {
          // best-effort enrichment only; the base message below still holds.
        }
        const periodTxt = start || end ? ` in ${start ?? '…'}–${end ?? '…'}` : '';
        return (
          `flow_ref "${flowRef}" and key "${key}" ARE valid — BIS has published this exact series ` +
          `— so this is a well-formed key with a genuinely empty result, not a malformed one. ` +
          `There is no data${periodTxt}` +
          `${lastPeriod ? `; its most recent published observation is ${lastPeriod}` : ''}.` +
          `${note} If this series looks discontinued or superseded, try fetch_dataset with no key ` +
          `for this flow_ref to see which keys are currently active (a euro-area country's national ` +
          `rate series, for example, is typically superseded by the aggregate code "XM").`
        );
      }

      // Key never matched any series BIS has ever published. Name the flow's
      // actual key dimensions, from the structure endpoint — ~12KB regardless
      // of flow size. The previous version fetched a period-bounded slice of
      // the WHOLE FLOW with full observations just to read its CSV header: on
      // WS_CBPOL that is tens of MB and killed the worker with a 1102, so the
      // diagnosis crashed before it could diagnose. The header was also the
      // wrong instrument — its columns include attributes (COMPILATION, TITLE,
      // OBS_VALUE, …), so it counted 15 "dimensions" on a flow whose key has 2.
      const structRes = await fetchBounded(
        `${BASE_URL}/structure/dataflow/BIS/${encodeURIComponent(id)}/${encodeURIComponent(version)}?references=datastructure`,
        8000,
        { headers: { Accept: 'application/vnd.sdmx.structure+json;version=2.0.0' } },
      );
      if (structRes.ok) {
        const struct = (await structRes.json()) as {
          data?: {
            dataStructures?: {
              dataStructureComponents?: { dimensionList?: { dimensions?: { id?: string }[] } };
            }[];
          };
        };
        const dims = (
          struct.data?.dataStructures?.[0]?.dataStructureComponents?.dimensionList?.dimensions ?? []
        )
          .map((d) => d.id ?? '')
          .filter(Boolean);
        if (dims.length) {
          const nParts = key.split('.').length;
          const overUnder =
            nParts !== dims.length
              ? ` Your key has ${nParts} dot-separated part${nParts === 1 ? '' : 's'} but this flow's key has ${dims.length} dimensions — that mismatch alone is enough for BIS to answer "no results."`
              : '';
          return (
            `BIS has never published a series matching key "${key}" under flow_ref "${flowRef}" — ` +
            `this is a malformed or wrong-value key, not a temporarily-empty one.${overUnder} Keys ` +
            `are positional over this flow's dimensions, in order: ${dims.join('.')} (leave a ` +
            `position empty to not filter on it, e.g. "${'.'.repeat(dims.length - 1)}"). Re-run ` +
            `fetch_dataset with no key and a bounded start_period/end_period to see the values ` +
            `actually present, then filter.`
          );
        }
      }
    }
    return generic;
  } catch {
    return generic;
  }
}

async function fetchDataset(flowRef: string, key: string, start?: string, end?: string, limit = 5000) {
  const url = buildDataUrl(flowRef, key);
  setCsvFormat(url);
  if (start) url.searchParams.set('startPeriod', start);
  if (end) url.searchParams.set('endPeriod', end);

  const res = await pwFetch(url.toString());
  if (!res.ok) {
    const body = await res.text();
    // BIS answers 404 both for "this flow doesn't exist" and "your dimension key
    // matched nothing". Say which, so a caller isn't left thinking the dataset
    // is gone when they simply over-filtered.
    if (res.status === 404) {
      // `user_error:` prefix, not because the message was wrong — it is one of
      // the better ones we ship — but because of where it was being filed. An
      // over-filtered dimension key was booking as blob4='error', the tier that
      // means "Pipeworx defect", and at 14 of 124 calls in a day that put bis on
      // the problem-tools list as our 11%-failure pack. It is nothing of the
      // sort: it is one caller walking dimension-key permutations, which is the
      // correct way to use an SDMX API when you don't know the key yet, and the
      // message below is what teaches them the right one. Misfiling it costs
      // twice — a phantom defect on our list, and a real defect crowded off it.
      throw new Error(`user_error: ${await diagnoseNoData(flowRef, key, start, end)}`);
    }
    // SDMX answers a rejected query with `<?xml …><message:Error>`; the raw
    // slice reached the caller as the document itself. summarizeErrorBody lifts
    // the fault text out and drops the envelope (fleet #712). `body` is already
    // read here, so httpError would find nothing left to mine.
    throw new Error(`BIS data error: ${res.status} — ${summarizeErrorBody(body) || 'no readable message'}`);
  }
  const body2 = await readCapped(res, MAX_CSV_BYTES);
  // On overflow, drop the final (possibly mid-row) line so parsing stays clean.
  const csv = body2.exceeded ? body2.text.slice(0, body2.text.lastIndexOf('\n') + 1) : body2.text;
  const rows = parseCsv(csv);
  if (rows.length === 0) return { flow_ref: flowRef, columns: [], count: 0, rows: [] };
  const header = rows[0];
  const plan = planColumns(header);
  const out: Record<string, string>[] = [];
  for (let i = 1; i < rows.length && out.length < limit; i++) {
    const r = rows[i];
    if (r.length === 1 && r[0] === '') continue;
    const obj: Record<string, string> = {};
    for (let c = 0; c < plan.names.length; c++) obj[plan.names[c]] = r[plan.from[c]] ?? '';
    out.push(obj);
  }
  return {
    flow_ref: flowRef,
    source_url: `https://stats.bis.org/statx/srs/data/${encodeURIComponent(flowRef.split(',')[1] ?? '')}`,
    columns: plan.names,
    truncated: body2.exceeded || rows.length - 1 > limit,
    ...(body2.exceeded && {
      note:
        `BIS's response passed ${Math.round(MAX_CSV_BYTES / 1048576)}MB and was cut off — these rows ` +
        `cover only the start of the range. Pass start_period/end_period (e.g. "2024") to get the ` +
        `window you actually want.`,
    }),
    count: out.length,
    rows: out,
  };
}

const CREDIT_GAP_FLOW = 'BIS,WS_CREDIT_GAP,1.0';

// WS_CREDIT_GAP publishes three series per country under one dimension. The
// letters mean nothing on their own, which is exactly why a caller handed the
// raw flow could not answer "what is the gap" even holding the right numbers.
const CG_DTYPE_FIELD: Record<string, 'credit_to_gdp_ratio' | 'trend' | 'gap'> = {
  A: 'credit_to_gdp_ratio',
  B: 'trend',
  C: 'gap',
};

// Names agents actually type, mapped to the code BIS publishes under. BIS's own
// labels are "Korea", "Türkiye", "Czechia", "Hong Kong SAR" and "Euro area", so
// plain-substring matching alone misses "South Korea", "Turkey" and "Eurozone".
const COUNTRY_ALIASES: Record<string, string> = {
  usa: 'US',
  'u.s.': 'US',
  'u.s.a.': 'US',
  america: 'US',
  'united states of america': 'US',
  uk: 'GB',
  britain: 'GB',
  'great britain': 'GB',
  england: 'GB',
  'south korea': 'KR',
  'republic of korea': 'KR',
  turkey: 'TR',
  turkiye: 'TR',
  'czech republic': 'CZ',
  'hong kong': 'HK',
  'russian federation': 'RU',
  eurozone: 'XM',
  'euro zone': 'XM',
  'euro area': 'XM',
};

/**
 * Every economy WS_CREDIT_GAP currently carries, read from BIS rather than
 * hardcoded so a country BIS adds or drops is right without a redeploy.
 * `lastNObservations=1` over the whole flow is one row per series -- 132 rows
 * for 44 economies -- so this stays cheap enough to run on the resolve path.
 */
async function gapCountries(): Promise<{ code: string; name: string }[]> {
  const url = buildDataUrl(CREDIT_GAP_FLOW, '');
  setCsvFormat(url);
  url.searchParams.set('lastNObservations', '1');
  const res = await fetchBounded(url.toString(), 12000);
  if (!res.ok) return [];
  const rows = parseCsv((await readCapped(res, 1024 * 1024)).text);
  if (rows.length < 2) return [];
  const plan = planColumns(rows[0]);
  const codeAt = plan.names.indexOf('BORROWERS_CTY');
  const nameAt = plan.names.indexOf('BORROWERS_CTY_label');
  if (codeAt < 0) return [];
  const seen = new Map<string, string>();
  for (let i = 1; i < rows.length; i++) {
    const code = rows[i][plan.from[codeAt]] ?? '';
    if (!code || seen.has(code)) continue;
    seen.set(code, (nameAt >= 0 ? rows[i][plan.from[nameAt]] : '') || code);
  }
  return [...seen].map(([code, name]) => ({ code, name })).sort((a, b) => a.code.localeCompare(b.code));
}

function matchCountry(input: string, list: { code: string; name: string }[]): string | null {
  const q = input.trim().toLowerCase();
  if (!q) return null;
  const alias = COUNTRY_ALIASES[q];
  if (alias) return alias;
  const exactCode = list.find((c) => c.code.toLowerCase() === q);
  if (exactCode) return exactCode.code;
  const exactName = list.find((c) => c.name.toLowerCase() === q);
  if (exactName) return exactName.code;
  const partial = list.filter((c) => c.name.toLowerCase().includes(q) || q.includes(c.name.toLowerCase()));
  return partial.length === 1 ? partial[0].code : null;
}

/**
 * The credit-to-GDP gap for one country, as a practitioner means it: the ratio,
 * its trend, and the difference, per quarter, already labelled and paired up.
 */
async function creditGap(country: string, start?: string, end?: string, limit = 20) {
  const raw = country.trim();
  // An ISO alpha-2 is the common case and needs no lookup; anything else does.
  let code = /^[A-Za-z]{2}$/.test(raw) ? raw.toUpperCase() : null;
  let known: { code: string; name: string }[] = [];
  if (!code) {
    known = await gapCountries();
    code = matchCountry(raw, known);
    if (!code) {
      return {
        found: false,
        reason: 'country_not_recognised',
        requested: country,
        hint:
          `BIS publishes credit-to-GDP gaps for ${known.length} economies; "${country}" did not match one. ` +
          `Pass an ISO alpha-2 code or one of these names.`,
        available: known,
      };
    }
  }

  const url = buildDataUrl(CREDIT_GAP_FLOW, `Q.${code}...`);
  setCsvFormat(url);
  if (start) url.searchParams.set('startPeriod', start);
  if (end) url.searchParams.set('endPeriod', end);
  const res = await pwFetch(url.toString());
  if (!res.ok) {
    // 404 here means the economy is not in this flow -- BIS covers 44, not the
    // world -- so say which ones it does cover instead of throwing. An agent
    // can act on a list; it cannot act on "no data".
    if (res.status === 404) {
      if (!known.length) known = await gapCountries();
      return {
        found: false,
        reason: 'country_not_covered',
        requested: country,
        resolved_code: code,
        hint:
          `BIS does not publish a credit-to-GDP gap for "${code}". Coverage is the ${known.length} ` +
          `economies listed here, plus the euro area aggregate "XM".`,
        available: known,
      };
    }
    throw await httpError(res, 'BIS data error');
  }

  const rows = parseCsv((await readCapped(res, MAX_CSV_BYTES)).text);
  if (rows.length < 2) {
    return {
      found: false,
      reason: 'no_observations_in_period',
      requested: country,
      resolved_code: code,
      hint: `BIS has no credit-to-GDP gap observations for ${code} in the requested period. Drop start_period/end_period to get its full published history.`,
    };
  }
  const plan = planColumns(rows[0]);
  const at = (n: string) => {
    const i = plan.names.indexOf(n);
    return i >= 0 ? plan.from[i] : -1;
  };
  const iPeriod = at('TIME_PERIOD');
  const iValue = at('OBS_VALUE');
  const iType = at('CG_DTYPE');
  const iCtyName = at('BORROWERS_CTY_label');

  // Three rows per quarter (ratio, trend, gap) collapse into one quarter.
  const byPeriod = new Map<string, Record<string, number | string>>();
  let countryName = code;
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const period = iPeriod >= 0 ? r[iPeriod] ?? '' : '';
    if (!period) continue;
    if (iCtyName >= 0 && r[iCtyName]) countryName = r[iCtyName];
    const field = CG_DTYPE_FIELD[(iType >= 0 ? r[iType] : '') ?? ''];
    if (!field) continue;
    const num = Number(iValue >= 0 ? r[iValue] : NaN);
    if (!Number.isFinite(num)) continue;
    const bucket = byPeriod.get(period) ?? { period };
    bucket[field] = Math.round(num * 100) / 100;
    byPeriod.set(period, bucket);
  }

  const capped = Math.min(Math.max(1, limit), 400);
  const all = [...byPeriod.values()].sort((a, b) => String(b.period).localeCompare(String(a.period)));
  const quarters = all.slice(0, capped);
  const latest = quarters[0] ?? null;

  return {
    found: quarters.length > 0,
    country: code,
    country_name: countryName,
    flow_ref: CREDIT_GAP_FLOW,
    source_url: 'https://stats.bis.org/statx/srs/data/WS_CREDIT_GAP',
    frequency: 'quarterly',
    borrowing_sector: 'private non-financial sector',
    units: 'percent of GDP for ratio and trend; percentage points of GDP for the gap',
    definition:
      'gap = credit_to_gdp_ratio - trend, where trend is a one-sided Hodrick-Prescott filter of the ratio. A positive gap means private non-financial credit is above its long-run trend; BIS uses this series as the common reference point for the Basel III countercyclical capital buffer.',
    latest,
    returned: quarters.length,
    total_quarters_available: all.length,
    quarters,
  };
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        cell += ch;
      }
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === ',') {
        row.push(cell);
        cell = '';
      } else if (ch === '\n') {
        row.push(cell);
        rows.push(row);
        row = [];
        cell = '';
      } else if (ch === '\r') {
        // skip
      } else {
        cell += ch;
      }
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export default { tools, callTool, meter: { credits: 1 } } satisfies McpToolExport;
