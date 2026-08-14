
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db_session
from app.models import Rule
from app.schemas import RuleCreate, RuleResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rules"])


@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RuleCreate):
    
    try:
        async with get_db_session() as db:
            rule = Rule(
                keyword=payload.keyword,
                dm_message=payload.dm_message,
            )

            db.add(rule)
            await db.flush()
            

            logger.info(f"Rule created successfully | rule_id={rule.rule_id}")

            return RuleResponse(
                rule_id=rule.rule_id,
                keyword=rule.keyword,
                dm_message=rule.dm_message,
            )

    except SQLAlchemyError as e:
        logger.error(f"Database error while creating rule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create rule"
        )