
from pydantic import BaseModel, Field, field_validator


class RuleCreate(BaseModel):

    keyword: str = Field(..., min_length=1, max_length=255)
    dm_message: str = Field(..., min_length=1)

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("keyword cannot be empty")
        return cleaned

    @field_validator("dm_message")
    @classmethod
    def validate_dm_message(cls, value: str) -> str:
        
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dm_message cannot be empty")
        return cleaned


class RuleResponse(BaseModel):
    """
    Response schema for a created rule.
    """

    rule_id: str
    keyword: str
    dm_message: str


class StatsResponse(BaseModel):
    """
    Response schema for GET /stats
    """

    sent: int
    failed: int
    queued: int
    duplicates_blocked: int