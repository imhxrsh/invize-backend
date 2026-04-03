# Frontend Auth Integration Guide

This project uses JWT access tokens and rotating refresh tokens. Refer to Swagger at `/docs` for full request/response schemas. This guide summarizes the logic and what the frontend should do.

## Overview
- Access Token: short‑lived JWT used in `Authorization: Bearer <token>`; returned by `/auth/login` and `/auth/refresh`.
- Refresh Token: long‑lived, rotated on every refresh, stored either as an HttpOnly cookie or returned in the `X-Refresh-Token` header (based on `REFRESH_TOKEN_TRANSPORT`).
- Composite Refresh Token format: `tokenId.rawToken`. Only the hash of `rawToken` is stored server‑side.
- Register does not issue tokens by default; login after register.

## Transport Modes
- Cookie mode (`REFRESH_TOKEN_TRANSPORT=cookie`):
  - `POST /auth/login` sets `refresh_token` as an HttpOnly cookie (path `/auth`).
  - `POST /auth/refresh` rotates the cookie automatically and returns a new access token in JSON.
  - `POST /auth/logout` revokes the session and deletes the cookie.
  - Cookie `secure` flag auto‑toggles: `false` on HTTP (local dev), `true` on HTTPS.
  - Default `SameSite=strict`. For cross‑origin apps, you may need `SameSite=none` and `secure=true`.
- Header mode (`REFRESH_TOKEN_TRANSPORT=header`):
  - `POST /auth/login` returns `X-Refresh-Token` header (composite token) and JSON body with the access token.
  - `POST /auth/refresh` expects `{ "refresh_token": "<composite>" }` and returns a new access token; rotated refresh token is returned via `X-Refresh-Token`.
  - `POST /auth/logout` expects `{ "refresh_token": "<composite>" }` and revokes the session.
  - CORS must expose `X-Refresh-Token` (`expose_headers=["X-Refresh-Token"]`).

## Endpoints Quick Ref
- `POST /auth/register` → returns `MeResponse` (id, email, roles). No tokens.
- `POST /auth/login` → returns `TokenResponse` (`access_token`); sets refresh cookie or returns `X-Refresh-Token`.
- `POST /auth/refresh` → rotates refresh token and returns a new `access_token`. Cookie/header behavior as above.
- `POST /auth/logout` → revokes refresh token/session; deletes cookie in cookie mode.
- `GET /auth/me` → returns current user. Requires `Authorization: Bearer <access_token>`.

## JWT Details
- Payload includes: `sub` (user id), `ver` (token version), `iat`, `exp`, `iss`, `aud`, `roles`.
- TTL: `ACCESS_TOKEN_TTL_MIN` minutes (from settings).

## Password Policy & Hashing
- Password length: 8–128 characters.
- Hashing: `pbkdf2_sha256` by default; existing `bcrypt` hashes still validate.
- Refresh tokens are hashed (same context) and only stored as hashes. The raw token is never persisted.

## Refresh Rotation & Reuse Detection
- On refresh, the old token is revoked and a new one is issued.
- If a revoked token is presented (reuse), the associated session is revoked to mitigate token theft.

## Frontend Usage Examples

### Cookie Transport
```ts
// Login (cookie set by server)
const res = await fetch('/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password }),
  credentials: 'include', // required for cross-origin
});
const { access_token } = await res.json();

// Use access token
await fetch('/protected', {
  headers: { Authorization: `Bearer ${access_token}` },
});

// Refresh
const refreshRes = await fetch('/auth/refresh', { method: 'POST', credentials: 'include' });
const { access_token: newAccess } = await refreshRes.json();

// Logout
await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
```

### Header Transport
```ts
// Login (read header)
const res = await fetch('/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password }),
});
const { access_token } = await res.json();
const refresh = res.headers.get('X-Refresh-Token');

// Refresh
const r = await fetch('/auth/refresh', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ refresh_token: refresh }),
});
const { access_token: newAccess } = await r.json();
const rotated = r.headers.get('X-Refresh-Token'); // store new value

// Logout
await fetch('/auth/logout', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ refresh_token: refresh }),
});
```

## CORS Notes
- For cookie transport across origins: set `credentials: 'include'` and configure backend CORS to allow credentials and your origin.
- For header transport: configure backend CORS `expose_headers=["X-Refresh-Token"]` so the browser can read the header.

## Swagger
- Full endpoint details are available at `/docs` (Swagger UI). Share this file plus Swagger with the frontend team.
- See also `docs/PROFILE_SECURITY_API.md` for Profile & Users endpoints, types, and integration notes.