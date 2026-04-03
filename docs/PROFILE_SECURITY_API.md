# User Profile & Security API

This document summarizes the Profile and Users endpoints, data models, and integration notes for the frontend team. For exact request/response schemas, refer to Swagger UI at `/docs` and the OpenAPI specification at `/openapi.json`.

## Overview
- Auth: JWT Bearer tokens in `Authorization: Bearer <access_token>`.
- Refresh: Rotating refresh tokens, transported via HttpOnly cookie or `X-Refresh-Token` header (see `AUTH_FRONTEND_INTEGRATION.md`).
- Persistence: Prisma Client Python with MongoDB.
- Static uploads: Avatars served from `/uploads/avatars/...`.

## Endpoints
- `GET /profile/context`
  - Purpose: Aggregate user view, organization, preferences, security summary, feature flags, and unread counts.
  - Auth: Bearer token required.
  - Response: `ProfileContext`.

- `PATCH /users/me`
  - Purpose: Update the current user’s profile fields.
  - Auth: Bearer token required.
  - Content-Type: `application/json`.
  - Body: `UpdateUserRequest` (partial allowed).
  - Response: `UserResponse`.

- `PUT /users/me/preferences`
  - Purpose: Upsert user preferences.
  - Auth: Bearer token required.
  - Content-Type: `application/json`.
  - Body: `PreferencesUpdateRequest` (partial allowed).
  - Response: `PreferencesResponse`.

- `POST /users/me/avatar`
  - Purpose: Upload or replace the user’s avatar.
  - Auth: Bearer token required.
  - Content-Type: `multipart/form-data` with `file`.
  - Response: `AvatarUploadResponse` with `avatar_url`.

- `GET /users/me/security`
  - Purpose: View recent security events and password metadata.
  - Auth: Bearer token required.
  - Response: `SecurityResponse`.

## Types
- `ProfileContext`
  - `user: UserView`
  - `org: OrgView | null`
  - `preferences: PreferencesView`
  - `security: SecuritySummary`
  - `feature_flags: FeatureFlags`
  - `unread_counts: UnreadCounts`

- `UserView`
  - `id: string`
  - `email: string (Email)`
  - `full_name?: string`
  - `phone?: string`
  - `locale?: string`
  - `time_zone?: string`
  - `avatar_url?: string`
  - `roles: string[]`
  - `permissions: string[]`

- `OrgView`
  - `id: string`
  - `name: string`
  - `logo_url?: string`
  - `domains: string[]`

- `PreferencesView`
  - `theme: string` (enum: `light` | `dark` | `system`)
  - `density: string` (enum: `comfortable` | `compact`)
  - `locale?: string`
  - `time_zone?: string`
  - `notifications_email: boolean`
  - `notifications_push: boolean`

- `SecuritySummary`
  - `password_last_changed_at?: string (ISO datetime)`
  - `recent_events: SecurityEvent[]`

- `SecurityEvent`
  - `type: string` (examples: `login_success`, `token_refreshed`, `token_reuse_detected`, `logout`)
  - `message?: string`
  - `created_at: string (ISO datetime)`

- `FeatureFlags`
  - `document_intelligence_enabled: boolean`
  - `beta_ui: boolean`

- `UnreadCounts`
  - `notifications: number`
  - `messages: number`

- `UpdateUserRequest`
  - `full_name?: string`
  - `phone?: string`
  - `locale?: string`
  - `time_zone?: string`

- `UserResponse`
  - Same shape as `UserView`.

- `PreferencesUpdateRequest`
  - `theme?: string` (enum: `light` | `dark` | `system`)
  - `density?: string` (enum: `comfortable` | `compact`)
  - `locale?: string`
  - `time_zone?: string`
  - `notifications_email?: boolean`
  - `notifications_push?: boolean`

- `PreferencesResponse`
  - Same shape as `PreferencesView`.

- `AvatarUploadResponse`
  - `avatar_url: string`

- `SecurityResponse`
  - Same shape as `SecuritySummary`.

## Auth Alignment
- Bearer JWT required for all endpoints above.
- `GET /auth/me` and `POST /auth/register` also return `roles[]` and `permissions[]` in their `MeResponse`.
- Refer to `docs/AUTH_FRONTEND_INTEGRATION.md` for login/refresh/logout flow details.

## CORS & Transport
- CORS defaults include common localhost origins; configure `CORS_ALLOW_ORIGINS` in `.env` if needed.
- Header transport exposes `X-Refresh-Token` to the browser; cookie transport requires `credentials: 'include'`.

## Error Contracts
- `401 Unauthorized`: missing/invalid/expired access token.
- `403 Forbidden`: insufficient permissions (route-level enforcement can be added).
- `422 Unprocessable Entity`: validation errors.

## Swagger & OpenAPI
- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
- Use these for exact request/response bodies, field names, enums, and required/optional flags.

## Notes
- Avatars are stored under `/uploads/avatars` and served statically.
- Security events are recorded for login success, refresh rotation, token reuse detection, and logout.
- `password_last_changed_at` is `null` unless a password change event is recorded.