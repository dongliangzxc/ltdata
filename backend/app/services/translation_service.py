"""Product-name translation with DB cache and Azure Translator provider."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.schemas import TranslationCache

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 2000


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def source_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def is_configured() -> bool:
    if not settings.TRANSLATION_ENABLED:
        return False
    if settings.TRANSLATION_PROVIDER == "mock":
        return True
    return bool(settings.AZURE_TRANSLATOR_KEY)


def _azure_translate(texts: list[str], target_lang: str) -> list[str]:
    endpoint = settings.AZURE_TRANSLATOR_ENDPOINT.rstrip("/")
    url = (
        f"{endpoint}/translate?api-version=3.0"
        f"&from=auto&to={quote(target_lang)}"
    )
    payload = json.dumps([{"Text": text} for text in texts]).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": settings.AZURE_TRANSLATOR_KEY,
    }
    if settings.AZURE_TRANSLATOR_REGION:
        headers["Ocp-Apim-Subscription-Region"] = settings.AZURE_TRANSLATOR_REGION
    request = Request(url, data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=settings.TRANSLATION_TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [
        str(item.get("translations", [{}])[0].get("text") or "")
        for item in data
    ]


def _mock_translate(texts: list[str], _target_lang: str) -> list[str]:
    return [f"【译】{text}" for text in texts]


def _call_provider(texts: list[str], target_lang: str) -> list[str]:
    provider = (settings.TRANSLATION_PROVIDER or "azure").lower()
    if provider == "mock":
        return _mock_translate(texts, target_lang)
    if provider == "azure":
        return _azure_translate(texts, target_lang)
    raise ValueError(f"不支持的翻译服务：{provider}")


def translate_texts(
    db: Session,
    texts: list[str],
    *,
    target_lang: str | None = None,
    source_lang: str = "auto",
) -> dict[str, str]:
    """Return {source_hash: translated_text}; never raise provider errors."""
    target = target_lang or settings.TRANSLATION_TARGET_LANG
    provider = (settings.TRANSLATION_PROVIDER or "azure").lower()

    normalized_by_hash: dict[str, str] = {}
    for text in texts:
        normalized = normalize_text(text)
        if not normalized:
            continue
        normalized_by_hash.setdefault(source_hash(normalized), normalized[:MAX_TEXT_LENGTH])

    if not normalized_by_hash:
        return {}

    hashes = list(normalized_by_hash)
    cached_rows = (
        db.query(TranslationCache.source_hash, TranslationCache.translated_text)
        .filter(
            TranslationCache.provider == provider,
            TranslationCache.target_lang == target,
            TranslationCache.source_hash.in_(hashes),
        )
        .all()
    )
    translations = {row.source_hash: row.translated_text for row in cached_rows}

    missing = [
        (text_hash, text)
        for text_hash, text in normalized_by_hash.items()
        if text_hash not in translations
    ]
    if not missing or not is_configured():
        return translations

    try:
        provider_texts = [text for _, text in missing]
        provider_results = _call_provider(provider_texts, target)
    except Exception:
        logger.exception("translation provider failed")
        return translations

    insert_rows = []
    for (text_hash, text), translated in zip(missing, provider_results):
        if not translated:
            continue
        translations[text_hash] = translated
        insert_rows.append({
            "source_hash": text_hash,
            "source_text": text,
            "source_lang": source_lang,
            "target_lang": target,
            "provider": provider,
            "translated_text": translated,
        })

    if insert_rows:
        try:
            db.execute(TranslationCache.__table__.insert(), insert_rows)
            db.commit()
        except IntegrityError:
            db.rollback()
        except Exception:
            db.rollback()
            logger.exception("failed to write translation cache")

    return translations
