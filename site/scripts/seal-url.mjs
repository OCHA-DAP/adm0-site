// Writes src/lib/tiles.sealed.json from TILES_URL and SITE_PASSWORD.
import { webcrypto as crypto } from "node:crypto";
import { writeFileSync } from "node:fs";

const url = process.env.TILES_URL ?? "/tiles";
const password = process.env.SITE_PASSWORD;
if (!password) throw new Error("SITE_PASSWORD is not set");

const iterations = 600000;
const salt = crypto.getRandomValues(new Uint8Array(16));
const iv = crypto.getRandomValues(new Uint8Array(12));
const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, [
  "deriveKey",
]);
const key = await crypto.subtle.deriveKey(
  { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
  material,
  { name: "AES-GCM", length: 256 },
  false,
  ["encrypt"],
);
const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(url)));
const b64 = (a) => Buffer.from(a).toString("base64");
writeFileSync(
  new URL("../src/lib/tiles.sealed.json", import.meta.url),
  JSON.stringify({ iterations, salt: b64(salt), iv: b64(iv), data: b64(data) }) + "\n",
);
console.log(`sealed ${url.startsWith("/") ? url : "tiles URL"}`);
