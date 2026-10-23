"""Infer month / platform / country from upload filenames."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.schemas import Country


PLATFORM_ALIASES = {
    "amazon": "amazon",
    "amz": "amazon",
    "亚马逊": "amazon",
    "shopee": "shopee",
    "虾皮": "shopee",
    "西皮": "shopee",
}

_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})-?(0[1-9]|1[0-2])(?!\d)")
_TOKEN_RE = re.compile(r"[_\-\s]+")


@dataclass
class FilenameMetadata:
    month: int | None = None
    platform: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    month_ambiguous: bool = False
    platform_ambiguous: bool = False
    country_ambiguous: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "platform": self.platform,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "month_ambiguous": self.month_ambiguous,
            "platform_ambiguous": self.platform_ambiguous,
            "country_ambiguous": self.country_ambiguous,
            "warnings": self.warnings,
        }


def _tokens(stem: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(stem) if token]


def parse_filename_metadata(filename: str | None, db: Session) -> FilenameMetadata:
    """Parse filename using the `YYYYMM_platform_country_description` convention.

    The parser also scans tokens anywhere in the filename.  If a field has
    multiple distinct candidates, it is treated as unresolved instead of being
    guessed, so bulk uploads cannot silently write the wrong month/platform.
    """
    result = FilenameMetadata()
    if not filename:
        return result

    stem = Path(filename).stem
    tokens = _tokens(stem)

    # Month: scan the full stem so YYYY-MM is not split by the tokenizer.
    months = {int(f"{year}{month}") for year, month in _MONTH_RE.findall(stem)}
    if len(months) > 1:
        result.month_ambiguous = True
    elif months:
        result.month = next(iter(months))

    # Platform aliases are token-level only, to avoid matching random text.
    platforms = {
        PLATFORM_ALIASES[token.lower()]
        for token in tokens
        if token.lower() in PLATFORM_ALIASES
    }
    if len(platforms) > 1:
        result.platform_ambiguous = True
    elif platforms:
        result.platform = next(iter(platforms))

    # Country: only active countries from the master table.
    countries = (
        db.query(Country)
        .filter(Country.is_active == 1)
        .order_by(Country.code)
        .all()
    )
    by_code = {country.code.upper(): country for country in countries}
    by_name = {country.name_cn.strip(): country for country in countries}
    by_en = {
        country.name_en.strip().lower(): country
        for country in countries
        if country.name_en and country.name_en.strip()
    }

    matched_countries: dict[str, Country] = {}
    for token in tokens:
        country = by_code.get(token.upper()) or by_name.get(token) or by_en.get(token.lower())
        if country:
            matched_countries[country.code] = country
    if len(matched_countries) > 1:
        result.country_ambiguous = True
    elif matched_countries:
        country = next(iter(matched_countries.values()))
        result.country_code = country.code
        result.country_name = country.name_cn

    return result
