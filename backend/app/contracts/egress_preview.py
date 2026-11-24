"""Safe, user-facing disclosure for one plan's real destination and input classes."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel,ConfigDict,Field


class PayloadSummary(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    text_count:int=Field(default=0,ge=0)
    reference_count:int=Field(default=0,ge=0)
    file_count:int=Field(default=0,ge=0)
    fragment_count:int=Field(default=0,ge=0)


class SourceEligibility(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    allowed:bool
    status:Literal["eligible","blocked","no_source_inputs","legacy_undeclared"]
    eligibility_fingerprint:str=Field(pattern=r"^[0-9a-f]{64}$")


class EgressPreview(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    mode:str
    policy_revision:int
    policy_revision_id:UUID|None
    actual_processing_location:Literal["local","external","unknown"]
    destination_revision_id:UUID|None
    destination_host:str|None
    purpose:str
    required_purposes:list[str]
    payload_summary:PayloadSummary
    source_eligibility:SourceEligibility
    blockers:list[str]
