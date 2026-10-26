"""Infer month / platform / country from upload filenames."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.schemas import Category, Country


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
_CATEGORY_BRACKET_RE = re.compile(r"\[([^\]]+)\]")


@dataclass
class FilenameMetadata:
    month: int | None = None
    platform: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    month_ambiguous: bool = False
    platform_ambiguous: bool = False
    country_ambiguous: bool = False
    category_ambiguous: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "platform": self.platform,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "category_code": self.category_code,
            "category_name": self.category_name,
            "month_ambiguous": self.month_ambiguous,
            "platform_ambiguous": self.platform_ambiguous,
            "country_ambiguous": self.country_ambiguous,
            "category_ambiguous": self.category_ambiguous,
            "warnings": self.warnings,
        }


def _tokens(stem: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(stem) if token]


def _match_category(categories: list[Category], value: str) -> Category | None:
    normalized = value.strip()
    if not normalized:
        return None
    by_code = {category.code.strip().lower(): category for category in categories}
    by_name = {category.name.strip(): category for category in categories}
    return by_code.get(normalized.lower()) or by_name.get(normalized)


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

    # Category: explicit bracket segment, e.g. 202609_amazon_US_[运动相机]_xxx.xlsx
    bracket_values = {
        value.strip()
        for value in _CATEGORY_BRACKET_RE.findall(stem)
        if value.strip()
    }
    categories = db.query(Category).all()
    if len(bracket_values) > 1:
        result.category_ambiguous = True
    elif bracket_values:
        value = next(iter(bracket_values))
        category = _match_category(categories, value)
        if category:
            result.category_code = category.code
            result.category_name = category.name
        else:
            result.warnings.append(f"文件名品类「{value}」未匹配到系统品类")
    elif len(tokens) >= 4:
        # Alternative format: YYYYMM_platform_country_category.xlsx
        # Category is the remaining tail, so codes with underscores like
        # action_cameras are reconstructed correctly.
        token_month = None
        if re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", tokens[0]):
            token_month = int(tokens[0])
        token_platform = PLATFORM_ALIASES.get(tokens[1].lower())
        token_country = (
            by_code.get(tokens[2].upper())
            or by_name.get(tokens[2])
            or by_en.get(tokens[2].lower())
        )
        if token_month and token_platform and token_country:
            tail = "_".join(tokens[3:])
            category = _match_category(categories, tail)
            if category:
                result.category_code = category.code
                result.category_name = category.name

    return result
