import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    return email


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class UserCreate(BaseModel):
    email: str
    full_name: str = Field(default="", max_length=200)
    password: str = Field(min_length=12, max_length=72)
    role: Literal["admin", "user"] = "user"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class UserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.role is None and self.is_active is None:
            raise ValueError("Provide a role or active status to update.")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Message cannot be empty.")
        return content


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_user_message(self):
        if self.messages[-1].role != "user":
            raise ValueError("The latest message must be from the user.")
        return self


class ChatResponse(BaseModel):
    reply: str
