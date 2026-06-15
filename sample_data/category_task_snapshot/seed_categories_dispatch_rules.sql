-- 可选：如果你的环境还没有品类和分发规则，可在数据库执行这些种子数据后再上传样例 Excel。
-- 注意：生产库执行前请先确认不会覆盖你已有同 code 的品类/规则。

INSERT INTO categories (code, name, created_at, updated_at)
VALUES
  ('soundbar', '回音壁', NOW(), NOW()),
  ('router', '路由器', NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), updated_at = NOW();

INSERT INTO dispatch_rules (category_code, platform, field, match_type, value, item_name_keyword, priority, is_active, created_at, updated_at)
VALUES
  ('soundbar', 'jd', 'category_lv2', 'contains', '回音壁', NULL, 10, 1, NOW(), NOW()),
  ('router', 'jd', 'category_lv2', 'contains', '路由器', NULL, 20, 1, NOW(), NOW());
