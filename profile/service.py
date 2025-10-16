from typing import Optional
from prisma import Prisma
from auth.dependencies import get_current_user
from .schemas import (
    ProfileContext,
    UserView,
    OrgView,
    PreferencesView,
    SecuritySummary,
    SecurityEvent,
    FeatureFlags,
    UnreadCounts,
)
from fastapi import Depends
from datetime import datetime


async def build_profile_context(prisma: Prisma, user) -> ProfileContext:
    org_view = None
    if getattr(user, "orgId", None):
        org = await prisma.org.find_unique(where={"id": user.orgId})
        if org:
            org_view = OrgView(id=org.id, name=org.name, logo_url=org.logoUrl, domains=org.domains or [])

    prefs = await prisma.userpreferences.find_unique(where={"userId": user.id})
    preferences_view = PreferencesView(
        theme=prefs.theme if prefs and prefs.theme else "system",
        density=prefs.density if prefs and prefs.density else "comfortable",
        locale=prefs.locale if prefs else None,
        time_zone=prefs.timeZone if prefs else None,
        notifications_email=prefs.notificationsEmail if prefs else True,
        notifications_push=prefs.notificationsPush if prefs else False,
    )

    events = await prisma.securityevent.find_many(where={"userId": user.id})
    # Sort by createdAt desc and take up to 5
    events_sorted = sorted(events, key=lambda e: e.createdAt, reverse=True)[:5]
    event_views = [
        SecurityEvent(type=e.type, message=getattr(e, "message", None), created_at=e.createdAt) for e in events_sorted
    ]

    security_view = SecuritySummary(
        password_last_changed_at=None,  # Can be inferred from events in future
        recent_events=event_views,
    )

    user_view = UserView(
        id=user.id,
        email=user.email,
        full_name=getattr(user, "fullName", None),
        phone=getattr(user, "phone", None),
        locale=getattr(user, "locale", None),
        time_zone=getattr(user, "timeZone", None),
        avatar_url=getattr(user, "avatarUrl", None),
        roles=user.roles or [],
        permissions=getattr(user, "permissions", []) or [],
    )

    flags = FeatureFlags(document_intelligence_enabled=True, beta_ui=False)
    unread = UnreadCounts(notifications=0, messages=0)

    return ProfileContext(
        user=user_view,
        org=org_view,
        preferences=preferences_view,
        security=security_view,
        feature_flags=flags,
        unread_counts=unread,
    )