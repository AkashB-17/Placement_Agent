from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, require_role
from app.db import get_profile, list_profiles, set_profile_role
from app.schemas import InviteRequest, ProfileOut, RoleUpdate
from app.services.supabase_admin import invite_user

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role("admin")


@router.get("/users", response_model=list[ProfileOut])
def list_users(_: CurrentUser = Depends(admin_only)) -> list[ProfileOut]:
    return [ProfileOut(**row) for row in list_profiles()]


@router.post("/invite", response_model=ProfileOut)
def invite(body: InviteRequest, _: CurrentUser = Depends(admin_only)) -> ProfileOut:
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Email is not valid.")
    user_id = invite_user(email)
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
