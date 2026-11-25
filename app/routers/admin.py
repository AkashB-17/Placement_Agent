from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import CurrentUser, require_role
from app.config import get_settings
from app.db import get_profile, list_profiles, set_profile_role
from app.schemas import AppSettingsOut, AppSettingsUpdate, InviteRequest, ProfileOut, RoleUpdate
from app.services import app_settings
from app.services.supabase_admin import invite_user

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role("admin")


def _set_password_url(request: Request) -> str | None:
    """Invite links should land on the web app's set-password page, on the site the admin
    is using. The Origin header is only trusted if it is an allowed CORS origin, so a forged
    header can't point invitation emails at another site."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin in {o.rstrip("/") for o in get_settings().cors_origins}:
        return f"{origin}/auth/callback?next=set-password"
    return None


@router.get("/users", response_model=list[ProfileOut])
def list_users(_: CurrentUser = Depends(admin_only)) -> list[ProfileOut]:
    return [ProfileOut(**row) for row in list_profiles()]


@router.post("/invite", response_model=ProfileOut)
def invite(body: InviteRequest, request: Request, _: CurrentUser = Depends(admin_only)) -> ProfileOut:
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Email is not valid.")
    user_id = invite_user(email, redirect_to=_set_password_url(request))
    set_profile_role(user_id, body.role)
    return ProfileOut(id=user_id, email=email, role=body.role)


@router.put("/users/{user_id}/role", response_model=ProfileOut)
def change_role(user_id: str, body: RoleUpdate, admin: CurrentUser = Depends(admin_only)) -> ProfileOut:
    if user_id == admin.id and body.role != "admin":
        # Prevents locking the last admin out by accident.
        raise HTTPException(status_code=409, detail="Admins cannot remove their own admin role.")
    profile = get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found.")
    set_profile_role(user_id, body.role)
    return ProfileOut(id=user_id, email=profile["email"], role=body.role)


@router.get("/me", response_model=ProfileOut)
def whoami(user: CurrentUser = Depends(require_role("student", "officer", "recruiter", "admin"))) -> ProfileOut:
    """Any signed-in user: shows who the token belongs to and their role."""
    return ProfileOut(id=user.id, email=user.email, role=user.role)


@router.get("/settings", response_model=AppSettingsOut)
def get_settings_endpoint(_: CurrentUser = Depends(admin_only)) -> AppSettingsOut:
    return AppSettingsOut(**app_settings.threshold_info())


@router.put("/settings", response_model=AppSettingsOut)
def update_settings(body: AppSettingsUpdate, user: CurrentUser = Depends(admin_only)) -> AppSettingsOut:
    """Change the college-wide auto-apply threshold. It applies at once to rankings, the
    recommended flag and auto-apply runs. Students' own bars stay as they are; the bar used
    is always the higher of theirs and this. Applications already made are not affected."""
    app_settings.set_auto_apply_threshold(body.auto_apply_threshold, None if user.id == "dev-admin" else user.id)
    return AppSettingsOut(**app_settings.threshold_info())
