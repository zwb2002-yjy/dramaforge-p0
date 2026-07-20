"""Public Pydantic schemas for access / auth (no password hashes)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.shared.enums import MemberRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    version: int


class MembershipCreate(BaseModel):
    user_id: UUID
    role: MemberRole = MemberRole.VIEWER


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    user_id: UUID
    role: MemberRole
    created_at: datetime


class CsrfRead(BaseModel):
    csrf_token: str
