"""Translation API for overseas product names."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.models.database import get_db
from app.models.schemas import User
from app.services.translation_service import (
    is_configured,
    normalize_text,
    source_hash,
    translate_texts,
)

router = APIRouter(prefix="/api/translation", tags=["translation"])


class TranslationIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=50)
    source_lang: str = "auto"
    target_lang: Optional[str] = None

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, values: list[str]) -> list[str]:
        cleaned = [str(value or "") for value in values]
        if any(len(value) > 2000 for value in cleaned):
            raise ValueError("单条文本不能超过 2000 字符")
        return cleaned


class TranslationItem(BaseModel):
    source_hash: str
    source_text: str
    translated_text: str


class TranslationOut(BaseModel):
    provider: str
    target_lang: str
    translations: list[TranslationItem]


@router.get("/status")
def translation_status(_current_user: User = Depends(get_current_user)):
    return {
        "enabled": bool(settings.TRANSLATION_ENABLED and is_configured()),
        "configured": is_configured(),
        "provider": settings.TRANSLATION_PROVIDER,
        "target_lang": settings.TRANSLATION_TARGET_LANG,
    }


@router.post("/translate", response_model=TranslationOut)
def translate(
    payload: TranslationIn,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    target = payload.target_lang or settings.TRANSLATION_TARGET_LANG
    normalized_hashes = [source_hash(normalize_text(text)) for text in payload.texts]
    translated = translate_texts(
        db,
        payload.texts,
        target_lang=target,
        source_lang=payload.source_lang,
    )
    return {
        "provider": settings.TRANSLATION_PROVIDER,
        "target_lang": target,
        "translations": [
            {
                "source_hash": text_hash,
                "source_text": text,
                "translated_text": translated.get(text_hash, ""),
            }
            for text, text_hash in zip(payload.texts, normalized_hashes)
        ],
    }
