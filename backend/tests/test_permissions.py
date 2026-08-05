from app.core.permissions import (
    PERMISSION_DATA_MANAGEMENT,
    PERMISSION_PROCESSING_WORKBENCH,
    PERMISSION_PRODUCT_MANAGEMENT,
    normalize_permissions,
    required_permission_for_path,
    user_has_permission,
    visible_category_codes,
)


class DummyUser:
    def __init__(self, *, is_admin=0, permissions=None, category_permissions=None):
        self.is_admin = is_admin
        self.permissions = permissions
        self.category_permissions = category_permissions


def test_admin_has_all_permissions():
    user = DummyUser(is_admin=1, permissions=[])
    assert user_has_permission(user, PERMISSION_DATA_MANAGEMENT)
    assert user_has_permission(user, PERMISSION_PROCESSING_WORKBENCH)
    assert user_has_permission(user, PERMISSION_PRODUCT_MANAGEMENT)


def test_normal_user_only_has_granted_permissions():
    user = DummyUser(permissions=[PERMISSION_DATA_MANAGEMENT])
    assert user_has_permission(user, PERMISSION_DATA_MANAGEMENT)
    assert not user_has_permission(user, PERMISSION_PROCESSING_WORKBENCH)


def test_admin_sees_all_category_codes():
    all_category_codes = ["category_lv0", "category_lv1", "category_lv2", "category_lv3"]
    user = DummyUser(is_admin=1, category_permissions=[])
    assert visible_category_codes(user, all_category_codes) == all_category_codes


def test_normal_user_sees_only_granted_category_codes():
    user = DummyUser(is_admin=0, category_permissions=["category_lv1", "category_lv3"])
    assert visible_category_codes(user, ["category_lv0", "category_lv1", "category_lv2", "category_lv3"]) == [
        "category_lv1",
        "category_lv3",
    ]


def test_normal_user_without_category_permissions_sees_all_category_codes():
    all_category_codes = ["category_lv0", "category_lv1"]
    user = DummyUser(is_admin=0, category_permissions=None)
    assert visible_category_codes(user, all_category_codes) == all_category_codes


def test_normalize_permissions_filters_unknown_values():
    assert normalize_permissions([PERMISSION_DATA_MANAGEMENT, "unknown", 123]) == [PERMISSION_DATA_MANAGEMENT]
    assert normalize_permissions(None) == []
    assert normalize_permissions("data_management") == []


def test_required_permission_preserves_confirmed_directory_mapping():
    assert required_permission_for_path("/api/categories") == PERMISSION_DATA_MANAGEMENT
    assert required_permission_for_path("/api/match/1") == PERMISSION_PROCESSING_WORKBENCH
    assert required_permission_for_path("/api/clean/jobs") == PERMISSION_PROCESSING_WORKBENCH
    assert required_permission_for_path("/api/metadata") == PERMISSION_PROCESSING_WORKBENCH
    assert required_permission_for_path("/api/workbench/query") == PERMISSION_PRODUCT_MANAGEMENT
    assert required_permission_for_path("/api/auth/me") is None


def test_admin_can_see_all_categories():
    user = DummyUser(is_admin=1, category_permissions=[])

    assert visible_category_codes(user, ["headphone", "speaker"]) == ["headphone", "speaker"]


def test_normal_user_only_sees_granted_categories_in_original_order():
    user = DummyUser(category_permissions=["speaker", "unknown"])

    assert visible_category_codes(user, ["headphone", "speaker", "tv"]) == ["speaker"]
