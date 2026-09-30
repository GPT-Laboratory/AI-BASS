// No-library Base64URL decode + JSON parse
export function decodeJwt(token) {
  try {
    const [, payload] = (token || "").split(".");
    if (!payload) return {};
    const base64 = payload
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const json = atob(base64);
    const utf8 = decodeURIComponent(Array.from(json, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join(""));
    return JSON.parse(utf8);
  } catch {
    return {};
  }
}

// Check if JWT token is expired
export function isTokenExpired(token) {
  if (!token) return true;

  try {
    const payload = decodeJwt(token);
    if (!payload.exp) return true;

    // Check if token expires within the next 30 seconds (buffer for network requests)
    const now = Math.floor(Date.now() / 1000);
    const expiry = payload.exp;

    return expiry <= now + 30;
  } catch {
    return true;
  }
}

// Check if JWT token is valid (exists and not expired)
export function isTokenValid(token) {
  return token && !isTokenExpired(token);
}
