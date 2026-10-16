from typing import Any


PERMISSION_DATA_MANAGEMENT = "data_management"
PERMISSION_PROCESSING_WORKBENCH = "processing_workbench"
PERMISSION_PRODUCT_MANAGEMENT = "product_management"

VALID_PERMISSIONS = {
    PERMISSION_DATA_MANAGEMENT,
    PERMISSION_PROCESSING_WORKBENCH,
    PERMISSION_PRODUCT_MANAGEMENT,
}

PERMISSION_LABELS = {
    PERMISSION_DATA_MANAGEMENT: "数据管理",
    PERMISSION_PROCESSING_WORKBENCH: "处理工作台",
    PERMISSION_PRODUCT_MANAGEMENT: "成品管理",
}

API_PERMISSION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/upload/templates", PERMISSION_DATA_MANAGEMENT),
    ("/api/upload", PERMISSION_DATA_MANAGEMENT),
    ("/api/dispatch", PERMISSION_DATA_MANAGEMENT),
    ("/api/rawdata", PERMISSION_DATA_MANAGEMENT),
    ("/api/categories", PERMISSION_DATA_MANAGEMENT),
    ("/api/match", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/clean", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/metadata", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/models", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/brands", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/url-mappings", PERMISSION_PROCESSING_WORKBENCH),
    ("/api/export", PERMISSION_PRODUCT_MANAGEMENT),
    ("/api/workbench", PERMISSION_PRODUCT_MANAGEMENT),
    ("/api/publish", PERMISSION_PRODUCT_MANAGEMENT),
)


def normalize_permissions(value: Any) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item in VALID_PERMISSIONS]


def normalize_category_permissions(value: Any) -> list[str]:
    return value or []


def visible_category_codes(user: Any, all_category_codes: list[str]) -> list[str]:
    if getattr(user, "is_admin", 0) == 1:
        return all_category_codes
    category_permissions = getattr(user, "category_permissions", None)
    if not category_permissions:
        return all_category_codes
    allowed = set(normalize_category_permissions(category_permissions))
    return [code for code in all_category_codes if code in allowed]


def validate_permissions(value: Any) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("permissions 必须是数组")
    invalid = [item for item in value if item not in VALID_PERMISSIONS]
    if invalid:
        raise ValueError(f"未知权限：{', '.join(map(str, invalid))}")
    return list(dict.fromkeys(value))


def user_has_permission(user: Any, permission_key: str) -> bool:
    if getattr(user, "is_admin", 0):
        return True
    return permission_key in normalize_permissions(getattr(user, "permissions", None))


def required_permission_for_path(path: str) -> str | None:
    for prefix, permission_key in API_PERMISSION_PREFIXES:
        if path.startswith(prefix):
            return permission_key
    return None


def is_admin_only_path(path: str) -> bool:
    return path.startswith("/api/users")
