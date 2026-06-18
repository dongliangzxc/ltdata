from app.core.permissions import (
    PERMISSION_DATA_MANAGEMENT,
    PERMISSION_PROCESSING_WORKBENCH,
    PERMISSION_PRODUCT_MANAGEMENT,
    normalize_permissions,
    required_permission_for_path,
    user_has_permission,
)


class DummyUser:
    def __init__(self, *, is_admin=0, permissions=None):
        self.is_admin = is_admin
        self.permissions = permissions


def test_admin_has_all_permissions():
    user = DummyUser(is_admin=1, permissions=[])
    assert user_has_permission(user, PERMISSION_DATA_MANAGEMENT)
    assert user_has_permission(user, PERMISSION_PROCESSING_WORKBENCH)
    assert user_has_permission(user, PERMISSION_PRODUCT_MANAGEMENT)


def test_normal_user_only_has_granted_permissions():
    user = DummyUser(permissions=[PERMISSION_DATA_MANAGEMENT])
    assert user_has_permission(user, PERMISSION_DATA_MANAGEMENT)
    assert not user_has_permission(user, PERMISSION_PROCESSING_WORKBENCH)


def test_normalize_permissions_filters_unknown_values():
    assert normalize_permissions([PERMISSION_DATA_MANAGEMENT, "unknown", 123]) == [PERMISSION_DATA_MANAGEMENT]
    assert normalize_permissions(None) == []
    assert normalize_permissions("data_management") == []


def test_required_permission_preserves_confirmed_directory_mapping():
    assert required_permission_for_path("/api/categories") == PERMISSION_DATA_MANAGEMENT
    assert required_permission_for_path("/api/match/1") == PERMISSION_PROCESSING_WORKBENCH
    assert required_permission_for_path("/api/clean/jobs") == PERMISSION_PROCESSING_WORKBENCH
    assert required_permission_for_path("/api/workbench/query") == PERMISSION_PRODUCT_MANAGEMENT
    assert required_permission_for_path("/api/auth/me") is None
