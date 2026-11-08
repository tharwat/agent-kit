#!/usr/bin/env node
/**
 * scrollcraft asset generator: Segmind async (v2) API. Replaces the upstream kie.mjs (fork change).
 *
 *   POST https://api.segmind.com/v2/{model}                { ...model input }  -> { request_id, status_url, response_url }
 *   GET  https://api.segmind.com/v2/requests/{id}/status   -> { status: QUEUED|PROCESSING|COMPLETED|FAILED, metrics }
 *   GET  https://api.segmind.com/v2/requests/{id}          -> { output | images[0].url | video.url, metrics.cost }
 *   POST https://workflows-api.segmind.com/upload-asset    { data_urls: [data:...] } -> { file_urls: [...] }
 *   GET  https://api.segmind.com/v1/get-user-credits       -> { credits, "free-credits" }
 *
 * Grounded 2026-10-15 against docs.segmind.com (async-inference, segmind-storage,
 * account-and-billing-apis) and the model pages for seedream-4.5 and kling-2.5-turbo. kling-2.1 was the first
 * choice (it is kie's v2-1-pro) but returned a provider 500 on every request on 2026-10-15, Segmind's own sample
 * image included, so the clip model is 2.5 turbo: same end-frame feature, newer, and cheaper.
 *
 * COMMANDS
 *   still  <prompt> <out.png> [--ar 16:9] [--ref a.png ...] [--size 2K]
 *          seedream-4.5. Text-to-image, or reference-guided with one or more --ref.
 *          Stills are cheap. Generate, look, reroll.
 *
 *   shot   <prompt> <in.png> <out.mp4> [--tail b.png] [--dur 5|10] [--ar 16:9|9:16|1:1]
 *          kling-2.5-turbo image-to-video (pro is its only mode). --tail pins the LAST frame, which is
 *          the whole trick behind a seamless chain: leg N's tail is leg N+1's head. Prices: references/assets.md.
 *
 *   cutout <in.png|https-url> <out.png>
 *          bria-remove-background. The subject on a transparent background, for a layered hero
 *          (references/hero-depth.md). Check the alpha over a contrasting ground before using it.
 *
 *   probe  print the account's credit balance and exit.
 *
 * A --ref / head / --tail may be an https URL (passed through) or a local jpg/png/webp, which is uploaded to
 * the account's Segmind Storage first so the model can read it.
 *
 * Env: SEGMIND_API_KEY, read from the nearest .env walking up from the cwd if not already set.
 * The key is sent only in the x-api-key header and is never printed.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const API = "https://api.segmind.com";
const UPLOAD = "https://workflows-api.segmind.com/upload-asset";

const MODELS = { still: "seedream-4.5", shot: "kling-2.5-turbo", cutout: "bria-remove-background" };

const STILL_ARS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"];
const SHOT_ARS = ["16:9", "9:16", "1:1"];
const SHOT_DURS = ["5", "10"];
const FAILED = ["FAILED", "ERROR", "CANCELLED", "CANCELED", "REJECTED", "TIMEOUT", "TIMED_OUT"];

// ---------------------------------------------------------------- key ----
/**
 * The key and where it came from: the environment, else the first .env walking up from cwd that SETS it
 * (a nearer .env without it does not stop the search). doctor.mjs imports this, so the preflight and the
 * generator can never disagree about whether a key exists. null when there is none.
 */
export function findKey(env = process.env, cwd = process.cwd()) {
  if (env.SEGMIND_API_KEY) return { key: env.SEGMIND_API_KEY, where: "env" };
  const hit = findEnvValue("SEGMIND_API_KEY", cwd);
  return hit && { key: hit.value, where: hit.where };
}

/** The first .env walking up from `start` that sets `name` to a non-empty value: {value, where} or null. */
export function findEnvValue(name, start) {
  const re = new RegExp(`^[ \\t]*${name}[ \\t]*=[ \\t]*(\\S.*?)[ \\t]*$`);
  let dir = path.resolve(start);
  for (let i = 0; i < 8; i++) {
    const p = path.join(dir, ".env");
    if (fs.existsSync(p)) {
      for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
        const m = line.match(re);
        const value = m && m[1].replace(/^["']|["']$/g, "");
        if (value) return { value, where: p };
      }
    }
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}
export function readKey(env = process.env, cwd = process.cwd()) {
  const hit = findKey(env, cwd);
  if (!hit) throw new Error("SEGMIND_API_KEY is not set and no .env walking up from " + cwd + " sets it");
  return hit.key;
}
let KEY = null;
const headers = () => ({ "x-api-key": (KEY ??= readKey()), "Content-Type": "application/json" });

// ------------------------------------------------------------- helpers ----
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Segmind's human reason from an error body, capped. Never echoes request headers, so never the key. */
export function reason(text) {
  const raw = String(text ?? "");
  try {
    const j = JSON.parse(raw);
    const r = j.error || j.message || j.detail || j.data?.message;
    if (r) return String(typeof r === "string" ? r : JSON.stringify(r)).slice(0, 300);
  } catch { /* not JSON: fall through to the slice */ }
  return raw.replace(/\s+/g, " ").slice(0, 300);
}

/** The result URL in a v2 response, for both image and video models; null when absent. */
export function resultUrl(rj) {
  const cands = [rj?.output, Array.isArray(rj?.output) ? rj.output[0] : null, rj?.images?.[0]?.url, rj?.video?.url, rj?.video_url];
  for (const v of cands) if (typeof v === "string" && /^https?:\/\//i.test(v)) return v;
  return null;
}

/** Validate a flag against its allowed values; a bad value refuses before anything is spent. */
export function oneOf(name, value, allowed) {
  if (!allowed.includes(String(value))) throw new Error(`${name} must be one of ${allowed.join(", ")} (got "${value}")`);
  return String(value);
}

/**
 * The image type from the file's own bytes, never its name: seedream returns JPEG even into a file named
 * .png, so the extension is not evidence. Anything that is not jpg/png/webp is refused (null).
 */
export function sniffImage(b) {
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b.length >= 8 && b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (b.length >= 12 && b.toString("latin1", 0, 4) === "RIFF" && b.toString("latin1", 8, 12) === "WEBP") return "image/webp";
  return null;
}

async function uploadLocal(file) {
  const abs = path.resolve(file);
  if (!fs.existsSync(abs)) throw new Error("input not found: " + abs);
  const bytes = fs.readFileSync(abs);
  const mime = sniffImage(bytes);
  if (!mime) throw new Error(`cannot upload ${path.basename(abs)}: not a jpg, png or webp`);
  // No retry: a dropped upload is unbilled and a retry could leave a second stored copy. Keep refs small (~150KB JPEG)
  // and upload one at a time; the Storage endpoint dropped ~700KB and concurrent uploads on 2026-10-15.
  const res = await fetch(UPLOAD, {
    method: "POST",
    headers: { ...headers(), accept: "application/json" },
    body: JSON.stringify({ data_urls: [`data:${mime};base64,${bytes.toString("base64")}`] }),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`upload ${path.basename(abs)} ${res.status}: ${reason(text)}`);
  let url = null;
  try { url = JSON.parse(text)?.file_urls?.[0]; } catch { /* handled below */ }
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) throw new Error(`upload ${path.basename(abs)}: no file url in response: ${reason(text)}`);
  return url;
}

// A local path becomes a hosted URL; an http(s) string passes straight through.
const asUrl = (v) => (/^https?:\/\//i.test(v) ? Promise.resolve(v) : uploadLocal(v));

async function run(model, input, { label, kind, timeoutMs }) {
  const sub = await fetch(`${API}/v2/${model}`, { method: "POST", headers: headers(), body: JSON.stringify(input) });
  const subText = await sub.text();
  if (!sub.ok) throw new Error(`${model} submit ${sub.status}: ${reason(subText)}`);
  let j;
  try { j = JSON.parse(subText); } catch { throw new Error(`${model} submit: not JSON: ${reason(subText)}`); }
  const id = j.request_id;
  if (!id) throw new Error(`${model} submit returned no request_id: ${reason(subText)}`);
  // Built from the id, never taken from the reply: these requests carry the key, so they only ever go to
  // api.segmind.com (the documented shape, docs.segmind.com async-inference).
  const { statusUrl, responseUrl } = requestUrls(id);
  // The full id: a failed or abandoned request can only be looked up later by it.
  process.stderr.write(`  ${label}: submitted ${model} request ${id}\n`);

  const t0 = Date.now();
  let delay = 4000;
  let billed = false;
  for (;;) {
    // A timeout here does not cancel the render: Segmind keeps it (and bills it) for an hour.
    if (Date.now() - t0 > timeoutMs) {
      throw new Error(`${label}: gave up waiting after ${Math.round((Date.now() - t0) / 1000)}s${billed ? " (the render IS finished and billed)" : ""}; fetch it within the hour from ${responseUrl}`);
    }
    await sleep(delay);
    delay = Math.min(delay * 1.25, 15000);
    // The render is already submitted and billed: a network blip while waiting must not abandon it.
    const st = await fetch(statusUrl, { headers: headers() }).catch((e) => {
      process.stderr.write(`  ${label}: network error while waiting (${e.cause?.code || e.message}), retrying\n`);
      return null;
    });
    if (!st) continue;
    if (!st.ok) {
      const body = await st.text().catch(() => "");
      if (pollAction(st.status) === "fail") throw new Error(`${label}: status ${st.status}: ${reason(body)} (request ${id})`);
      process.stderr.write(`  ${label}: status ${st.status}, retrying\n`);
      continue;
    }
    const sj = await st.json().catch(() => ({}));
    const state = String(sj.status || "").toUpperCase();
    if (FAILED.includes(state)) throw new Error(`${label}: Segmind reported ${state}: ${reason(JSON.stringify(sj))}`);
    if (state !== "COMPLETED") {
      process.stderr.write(`  ${label}: ${state || "queued"} (${Math.round((Date.now() - t0) / 1000)}s)\n`);
      continue;
    }
    // COMPLETED = billed: log the spend NOW, once, before anything below can throw (a bad result body,
    // no URL, the deadline). A network blip or a retryable status on the result fetch goes round the loop
    // again (the status stays COMPLETED), bounded by the same deadline; only a real answer ends it.
    if (!billed) {
      billed = true;
      logSpend({ model, cost: sj.metrics?.cost ?? null, kind, seconds: input.duration });
    }
    const rr = await fetch(responseUrl, { headers: headers() }).catch((e) => {
      process.stderr.write(`  ${label}: network error fetching the result (${e.cause?.code || e.message}), retrying\n`);
      return null;
    });
    if (!rr) continue;
    const rText = await rr.text().catch(() => null);
    if (rText === null) continue;
    if (!rr.ok) {
      if (pollAction(rr.status) === "fail") throw new Error(`${label}: result ${rr.status}: ${reason(rText)} (request ${id})`);
      continue;
    }
    let rj;
    try { rj = JSON.parse(rText); } catch { throw new Error(`${label}: result not JSON: ${reason(rText)} (request ${id})`); }
    const url = resultUrl(rj);
    if (!url) throw new Error(`${label}: completed with no result url: ${reason(rText)} (request ${id})`);
    // metrics.remaining_credits is not printed: observed 2026-10-15 it is the balance BEFORE this charge. `probe` reads the real one.
    const cost = rj.metrics?.cost ?? sj.metrics?.cost ?? null;
    // Printed before the download: if the download then fails, the operator still has the link (Segmind
    // keeps it 1 hour). The spend was already logged when the status went COMPLETED.
    process.stderr.write(`  ${label}: result ${url}\n`);
    return { url, cost };
  }
}

/** The status and result URLs for a request id — always on api.segmind.com. */
export function requestUrls(id) {
  const base = `${API}/v2/requests/${encodeURIComponent(id)}`;
  return { statusUrl: `${base}/status`, responseUrl: base };
}

/**
 * What a non-2xx while waiting on a SUBMITTED (billed) render means. 404 (the status page is not there
 * yet), 408, 429 (rate limit) and 5xx are transient: keep waiting. Any other 4xx is Segmind's answer
 * (422 = the render FAILED, observed 2026-10-15; 401 = bad key): stop.
 */
export function pollAction(status) {
  if (status === 404 || status === 408 || status === 429 || status >= 500) return "retry";
  return "fail";
}

/**
 * Report a billed call the moment it is billed, on stderr, as one JSON line a wrapper can collect
 * (`spend: {...}`). Best-effort: a reporting failure warns, never fails a render that is already paid for.
 * The project's root (four levels up from this script once installed under .claude/skills/) is where
 * optional dependencies such as sharp are resolved from.
 */
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
function logSpend({ model, cost, kind, seconds }) {
  try {
    process.stderr.write(`  spend: ${JSON.stringify({ provider: "segmind", model, purpose: `scrollcraft-${kind}`, ...spendFields(cost, kind, seconds) })}\n`);
  } catch (e) {
    process.stderr.write(`  note: spend not reported (${e.message}); cost $${cost ?? "?"}\n`);
  }
}

/**
 * The usage fields for one billed call. A cost Segmind did not report stays UNREPORTED (never 0, which would
 * read as "free"); the reader prices it from the published rates instead: per image for a still, per second
 * of clip for a shot.
 */
export function spendFields(cost, kind, seconds) {
  const n = cost === null || cost === undefined || cost === "" ? NaN : Number(cost);
  return {
    ...(Number.isFinite(n) ? { reportedCost: n } : {}),
    ...(kind === "shot" ? { durationSeconds: Number(seconds) || 5 } : { unitCount: 1 }),
  };
}

/**
 * True only when some pixel of the image is actually transparent (sharp's `isOpaque` reads the pixels; an
 * alpha CHANNEL that is opaque everywhere is still an opaque box). Throws when sharp cannot be loaded: a check that
 * cannot run must not pass.
 */
export async function hasTransparency(file) {
  const sharp = createRequire(path.join(REPO, "package.json"))("sharp");
  const { isOpaque } = await sharp(file).stats();
  return isOpaque === false;
}

/** The media type from a file's own bytes (jpg/png/webp, mp4/mov, webm); null when it is none of them. */
export function sniffMedia(b) {
  const img = sniffImage(b);
  if (img) return img;
  if (b.length >= 12 && b.toString("latin1", 4, 8) === "ftyp") return "video/mp4";
  if (b.length >= 4 && b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3) return "video/webm";
  return null;
}

/**
 * Download a finished render. The bytes decide, not the CDN's content-type (S3-style hosts often say
 * application/octet-stream). The render is already billed, so bytes that are NOT the expected kind are still
 * kept, beside `out` as `<out>.download`, and the error names that file: nothing paid for is thrown away, and
 * nothing that is not an image/video lands at the path the page will reference.
 */
async function download(url, out, kind) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download ${res.status} ${url} (Segmind keeps a result for 1 hour)`);
  const bytes = Buffer.from(await res.arrayBuffer());
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  const got = sniffMedia(bytes);
  if (!got || !got.startsWith(kind + "/")) {
    const kept = path.resolve(out) + ".download";
    fs.writeFileSync(kept, bytes);
    throw new Error(`download: expected ${kind}, got ${got || "unrecognised bytes"} (content-type "${res.headers.get("content-type") || "none"}"); kept as ${kept}`);
  }
  fs.writeFileSync(path.resolve(out), bytes);
  const want = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4" }[path.extname(out).toLowerCase()];
  if (want && got !== want) process.stderr.write(`  note: ${path.basename(out)} holds ${got} data (browsers and ffmpeg read it by content)\n`);
  return out;
}

/**
 * The download of a billed render, retried on a network error (3 tries). A wrong-kind result is not retried
 * (download() already kept its bytes). On the last failure the error names the result URL, which Segmind
 * keeps for 1 hour, so the paid render can still be fetched by hand.
 */
async function downloadWithRetry(url, out, kind, tries = 3) {
  for (let i = 1; ; i++) {
    try {
      return await download(url, out, kind);
    } catch (e) {
      // A network error or a 5xx from the file host is transient; anything else (a 404, wrong bytes) is not.
      const network = /fetch failed|ECONNRESET|ETIMEDOUT|ENOTFOUND|socket|^download 5\d\d /i.test(`${e.message} ${e.cause?.code ?? ""}`);
      if (!network) throw e;
      if (i >= tries) throw new Error(`download failed ${tries} times (${e.cause?.code || e.message}); fetch it within the hour from ${url}`);
      process.stderr.write(`  download: network error (${e.cause?.code || e.message}), retry ${i}/${tries - 1}\n`);
      await sleep(3000 * i);
    }
  }
}

const costLine = (r) => `  cost $${r.cost ?? "?"}\n`;

export function flag(argv, name, dflt = null) {
  const i = argv.indexOf(name);
  return i > -1 && argv[i + 1] ? argv[i + 1] : dflt;
}
export function flags(argv, name) {
  const out = [];
  argv.forEach((a, i) => { if (a === name && argv[i + 1]) out.push(argv[i + 1]); });
  return out;
}

/** The kling-2.5-turbo request body for a shot, validated before any upload or spend. Exported for probes. */
export function shotInput(rest) {
  const tail = flag(rest, "--tail");
  return {
    tail,
    input: {
      prompt: rest[0],
      duration: Number(oneOf("--dur", flag(rest, "--dur", "5"), SHOT_DURS)),
      aspect_ratio: oneOf("--ar", flag(rest, "--ar", "16:9"), SHOT_ARS),
      mode: "pro",
      // Camera-move clips are graded on smoothness, so the negative prompt
      // targets exactly what breaks a scrub: judder, warping, cuts.
      negative_prompt: "blur, distortion, low quality, warping, morphing, jitter, flicker, text, watermark, cut, scene change",
      cfg_scale: 0.5,
    },
  };
}

// ---------------------------------------------------------------- main ----
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const [cmd, ...rest] = process.argv.slice(2);
  try {
    if (cmd === "probe") {
      const r = await fetch(`${API}/v1/get-user-credits`, { headers: headers() });
      const text = await r.text();
      if (!r.ok) throw new Error(`credits ${r.status}: ${reason(text)}`);
      const j = JSON.parse(text);
      console.log(`credit: $${j.credits} (free $${j["free-credits"] ?? 0})`);

    } else if (cmd === "still") {
      const [prompt, out] = rest;
      if (!prompt || !out) throw new Error('usage: segmind.mjs still "<prompt>" <out.png> [--ar 16:9] [--ref a.png] [--size 2K]');
      const input = {
        prompt,
        aspect_ratio: oneOf("--ar", flag(rest, "--ar", "16:9"), STILL_ARS),
        size: oneOf("--size", flag(rest, "--size", "2K"), ["1K", "2K", "4K"]),
        max_images: 1,
      };
      const refs = flags(rest, "--ref");
      // one upload at a time: the Storage endpoint dropped concurrent uploads
      if (refs.length) { input.image_input = []; for (const r of refs) input.image_input.push(await asUrl(r)); }
      const r = await run(MODELS.still, input, { label: path.basename(out), kind: "still", timeoutMs: 10 * 60 * 1000 });
      await downloadWithRetry(r.url, out, "image");
      process.stderr.write(costLine(r));
      console.log(out);

    } else if (cmd === "shot") {
      const [prompt, head, out] = rest;
      if (!prompt || !head || !out) {
        throw new Error('usage: segmind.mjs shot "<prompt>" <head.png> <out.mp4> [--tail b.png] [--dur 5|10] [--ar 16:9|9:16|1:1]');
      }
      const { tail, input } = shotInput(rest);
      input.image_url = await asUrl(head);
      if (tail) input.tail_image_url = await asUrl(tail);
      const r = await run(MODELS.shot, input, { label: path.basename(out), kind: "shot", timeoutMs: 20 * 60 * 1000 });
      await downloadWithRetry(r.url, out, "video");
      process.stderr.write(costLine(r));
      console.log(out);

    } else if (cmd === "cutout") {
      const [src, out] = rest;
      if (!src || !out) throw new Error("usage: segmind.mjs cutout <in.png|https-url> <out.png>");
      if (path.extname(out).toLowerCase() !== ".png") throw new Error("cutout: the output must be a .png (it carries alpha)");
      const input = { image: await asUrl(src), preserve_alpha: true };
      const r = await run(MODELS.cutout, input, { label: path.basename(out), kind: "cutout", timeoutMs: 5 * 60 * 1000 });
      // downloaded BESIDE `out` and checked there: only a verified cutout replaces what `out` holds (code review R2-4)
      const staged = path.resolve(out).replace(/\.png$/i, `.incoming-${Date.now()}.png`);
      await downloadWithRetry(r.url, staged, "image");
      process.stderr.write(costLine(r));
      let ok = false;
      try {
        ok = await hasTransparency(staged);
      } catch (e) {
        throw new Error(`cutout: could not check the result for transparency (${e.message}); kept as ${staged}`);
      }
      // no transparent pixel = an opaque box over everything behind it; the render is paid for, so it is kept
      if (!ok) throw new Error(`cutout: the result has no transparent pixels; kept as ${staged}`);
      fs.renameSync(staged, path.resolve(out));
      console.log(out);

    } else {
      console.error(`scrollcraft asset generator (Segmind)

  node segmind.mjs probe
  node segmind.mjs still "<prompt>" <out.png> [--ar 16:9] [--ref ref.png] [--size 2K]
  node segmind.mjs shot  "<prompt>" <head.png> <out.mp4> [--tail tail.png] [--dur 5|10] [--ar 16:9|9:16|1:1]
  node segmind.mjs cutout <in.png|url> <out.png>
`);
      process.exit(1);
    }
  } catch (err) {
    // Node's network errors say only "fetch failed"; the cause (ECONNRESET, a TLS or DNS code) is the reason.
    const cause = err.cause ? ` (${err.cause.code || err.cause.message || err.cause})` : "";
    console.error("ERROR:", err.message + cause);
    // exitCode, not exit(): let pending stderr writes about a billed call land.
    process.exitCode = 1;
  }
}
