"""Public Pydantic schemas for access / auth (no password hashes)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class BootstrapStatusRead(BaseModel):
    owner_initialized: bool
    registration_available: bool
    public_registration_enabled: bool


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    version: int


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CsrfRead(BaseModel):
    csrf_token: str
