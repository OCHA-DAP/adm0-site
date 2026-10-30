import sealed from "$lib/tiles.sealed.json";

// The tiles base URL ships only as AES-GCM ciphertext, keyed by PBKDF2 of the password.
export async function unlock(password: string): Promise<string | null> {
  const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, [
    "deriveKey",
  ]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: bytes(sealed.salt), iterations: sealed.iterations, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
  try {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(sealed.iv) }, key, bytes(sealed.data));
    return new TextDecoder().decode(plain);
  } catch {
    return null;
  }
}
