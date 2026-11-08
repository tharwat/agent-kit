#!/usr/bin/env node
/**
 * scrollcraft static server.
 *
 * A scrollcraft page cannot be verified from file://. The engine fetches each
 * clip as a Blob, and file:// fetches are blocked by CORS in every browser, so
 * the page silently falls back to posters and looks fine while proving nothing.
 * Serve it.
 *
 *   node serve.mjs --root builds/perkform --port 4500
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i > -1 && argv[i + 1] ? argv[i + 1] : d; };

const ROOT = path.resolve(arg("--root", "."));
const PORT = parseInt(arg("--port", "4500"), 10);

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".json": "application/json",
  ".mp4": "video/mp4", ".webm": "video/webm",
  ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
  ".svg": "image/svg+xml", ".woff2": "font/woff2",
};

/**
 * The request path → a file under root, or a refusal. A malformed escape is a 400 (it used to throw
 * and kill the server); a path that leaves root (checked against root PLUS a separator, so a sibling folder
 * sharing root's name as a prefix is refused) or that names a dotfile anywhere (.env, .git) is a 403.
 */
export function resolveRequest(root, rawUrl) {
  let url;
  try { url = decodeURIComponent(String(rawUrl).split("?")[0]); } catch { return { status: 400 }; }
  const file = path.join(root, url === "/" ? "/index.html" : url);
  if (file !== root && !file.startsWith(root + path.sep)) return { status: 403 };
  if (path.relative(root, file).split(path.sep).some((part) => part.startsWith("."))) return { status: 403 };
  return { file };
}

/**
 * One `bytes=` range → {start, end} (inclusive), "unsatisfiable", or null (no/unsupported header → whole
 * file). Handles `a-b`, `a-` and the suffix form `-n`; a multi-range request is served whole.
 */
export function parseRange(header, size) {
  const m = /^bytes=(\d*)-(\d*)$/.exec(String(header ?? "").trim());
  if (!m || (m[1] === "" && m[2] === "")) return null;
  let start, end;
  if (m[1] === "") { const n = Number(m[2]); if (n === 0) return "unsatisfiable"; start = Math.max(0, size - n); end = size - 1; }
  else { start = Number(m[1]); end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1); }
  if (start >= size || start > end) return "unsatisfiable";
  return { start, end };
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) http.createServer((req, res) => {
  const r = resolveRequest(ROOT, req.url);
  if (r.status) { res.writeHead(r.status).end(r.status === 400 ? "bad request" : "forbidden"); return; }
  let file = r.file;
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
  if (!fs.existsSync(file)) { res.writeHead(404).end("not found"); return; }

  const ext = path.extname(file).toLowerCase();
  const stat = fs.statSync(file);
  const headers = {
    "Content-Type": TYPES[ext] || "application/octet-stream",
    // No caching: verification loops re-shoot the same URLs after edits, and a
    // cached clip or stylesheet makes you screenshot the previous build.
    "Cache-Control": "no-store",
    "Accept-Ranges": "bytes",
  };
  // Honour Range like a real host does, so a <video src> seeks here the way it will live.
  const range = parseRange(req.headers.range, stat.size);
  if (range === "unsatisfiable") {
    res.writeHead(416, { ...headers, "Content-Range": `bytes */${stat.size}` }).end();
    return;
  }
  const { start, end } = range || { start: 0, end: stat.size - 1 };
  res.writeHead(range ? 206 : 200, {
    ...headers,
    "Content-Length": stat.size === 0 ? 0 : end - start + 1,
    ...(range ? { "Content-Range": `bytes ${start}-${end}/${stat.size}` } : {}),
  });
  if (stat.size === 0) { res.end(); return; }
  // A read error (permissions, a file removed mid-request) ends this response, never the server.
  fs.createReadStream(file, { start, end }).on("error", () => res.destroy()).pipe(res);
  // This machine only: on every interface, anyone on the same network could read the served folder.
}).listen(PORT, "127.0.0.1", () => {
  console.log(`scrollcraft: ${ROOT}\n  http://localhost:${PORT}`);
});
