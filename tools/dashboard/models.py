# -*- coding: utf-8 -*-

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


OpusModel = Literal["claude-opus-4-8", "sonnet", "claude-sonnet-5", "claude-haiku-4-5"]
OpusEffort = Literal["low", "medium", "high", "xhigh", "max"]


class DecideRequest(BaseModel):


    decision: Literal["approved", "manual", "ignore"]
    model: Optional[OpusModel] = None
    effort: Optional[OpusEffort] = None


class InvokeOpusRequest(BaseModel):


    prompt: str = Field(default="", max_length=20000)
    subject: str = Field(default="", max_length=1000)
    model: Optional[OpusModel] = None
    effort: Optional[OpusEffort] = None


class DispatchRequest(BaseModel):


    branch: Literal["opus", "alert"]
    subject: str = Field(default="", max_length=1000)
    prompt: str = Field(default="", max_length=20000)
    model: Optional[OpusModel] = None
    effort: Optional[OpusEffort] = None


class ModeRequest(BaseModel):


    dry_run: bool


class PauseRequest(BaseModel):


    paused: bool


class ChatRequest(BaseModel):

    message: str = Field(min_length=1, max_length=20000)
    session_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-fA-F-]{8,64}$")


class ChatAttachment(BaseModel):


    name: str = Field(default="file", max_length=255)
    text: Optional[str] = Field(default=None, max_length=12_000_000)
    b64: Optional[str] = Field(default=None, max_length=12_000_000)


class ChatSendRequest(BaseModel):


    message: str = Field(default="", max_length=20000)
    subject: str = Field(default="", max_length=1000)


    std_prompt: bool = False
    model: Optional[OpusModel] = None
    effort: Optional[OpusEffort] = None
    attachments: Optional[List[ChatAttachment]] = Field(default=None, max_length=6)


class AgentConfigRequest(BaseModel):


    poll_seconds: Optional[int] = None
    max_mail_age_minutes: Optional[int] = None
    max_issues_per_hour: Optional[int] = None
    query_id: Optional[int] = None
    max_calls_route: Optional[int] = None
    max_calls_intent: Optional[int] = None

    role_chief_engineer: Optional[int] = None
    role_engineer: Optional[int] = None

    messenger_telegram: Optional[bool] = None
    messenger_ntfy: Optional[bool] = None
    telegram_chat_id: Optional[str] = None
    ntfy_topic: Optional[str] = None

    healthscript_cld_off: Optional[bool] = None
    mail_enabled: Optional[bool] = None

    take_chief: Optional[bool] = None
    take_engineer: Optional[bool] = None


class RedmineAccountRequest(BaseModel):


    name: str = Field(min_length=1, max_length=64)
    api_key: Optional[str] = None
    url: Optional[str] = None
    label: Optional[str] = None
    make_active: bool = False


class RedmineActiveRequest(BaseModel):

    name: str = Field(min_length=1, max_length=64)


class RoutingEditRequest(BaseModel):


    action: Literal["add", "delete"]
    key: str = Field(min_length=1)
    project_id: Optional[int] = None
    client: Optional[str] = None
