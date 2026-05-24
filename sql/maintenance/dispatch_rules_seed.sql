-- P11 dispatch rules seed
-- 品类：projector / tablet / edu_tablet / camera / smart_lock / monitor / laptop / router / dashcam / power_bank
-- 平台：jd / tmall
-- 生成日期：2026-05-15

INSERT INTO dispatch_rules (category_code, platform, field, match_type, value, item_name_keyword, priority, is_active) VALUES

-- ───── 投影机 jd ─────
('projector', 'jd', 'category_lv2', 'contains', '投影机', NULL, 100, 1),
('projector', 'jd', 'category_lv2', 'contains', '平板电视', '激光', 110, 1),

-- ───── 投影机 tmall ─────
('projector', 'tmall', 'category_lv2', 'contains', '投影仪', NULL, 100, 1),

-- ───── 智能平板 jd ─────
('tablet', 'jd', 'category_lv2', 'equals', '平板电脑', NULL, 100, 1),
('tablet', 'jd', 'category_lv2', 'equals', '笔记本', '二合一', 110, 1),

-- ───── 智能平板 tmall ─────
('tablet', 'tmall', 'category_lv1', 'equals', '平板电脑/MID', NULL, 100, 1),
('tablet', 'tmall', 'category_lv1', 'equals', '笔记本电脑', '二合一', 110, 1),

-- ───── 电子教育 jd ─────
('edu_tablet', 'jd', 'category_lv1', 'equals', '电子教育', NULL, 100, 1),

-- ───── 电子教育 tmall ─────
('edu_tablet', 'tmall', 'category_lv1', 'equals', '智能教育学习用品', NULL, 100, 1),
('edu_tablet', 'tmall', 'category_lv2', 'equals', '电子办公/学习设备', NULL, 100, 1),

-- ───── 摄像头 jd ─────
('camera', 'jd', 'category_lv2', 'contains', '安防监控', NULL, 100, 1),
('camera', 'jd', 'category_lv2', 'contains', '监控摄像', NULL, 100, 1),

-- ───── 摄像头 tmall ─────
('camera', 'tmall', 'category_lv2', 'contains', '视频监控', NULL, 100, 1),
('camera', 'tmall', 'category_lv2', 'contains', '网络设备', NULL, 100, 1),
('camera', 'tmall', 'category_lv2', 'contains', '智能摄像', NULL, 100, 1),
('camera', 'tmall', 'category_lv2', 'contains', '监控器材及系统', NULL, 100, 1),

-- ───── 智能门锁 jd ─────
('smart_lock', 'jd', 'category_lv2', 'contains', '电子锁', NULL, 100, 1),
('smart_lock', 'jd', 'category_lv2', 'contains', '机械锁', NULL, 100, 1),

-- ───── 智能门锁 tmall ─────
('smart_lock', 'tmall', 'category_lv2', 'contains', '智能锁/电子锁', NULL, 100, 1),

-- ───── 显示器 jd ─────
('monitor', 'jd', 'category_lv2', 'contains', '显示器', NULL, 100, 1),
('monitor', 'jd', 'category_lv2', 'contains', '台式机', NULL, 100, 1),
('monitor', 'jd', 'category_lv2', 'contains', '一体机', NULL, 100, 1),

-- ───── 显示器 tmall ─────
('monitor', 'tmall', 'category_lv2', 'contains', '显示器/显示屏/显示器配件', NULL, 100, 1),

-- ───── 笔记本 jd ─────
('laptop', 'jd', 'category_lv2', 'contains', '笔记本', NULL, 100, 1),
('laptop', 'jd', 'category_lv2', 'contains', '游戏本', NULL, 100, 1),

-- ───── 笔记本 tmall ─────
('laptop', 'tmall', 'category_lv1', 'contains', '笔记本电脑', NULL, 100, 1),

-- ───── 路由器 jd ─────
('router', 'jd', 'category_lv2', 'equals', '路由器', NULL, 100, 1),
('router', 'jd', 'category_lv2', 'equals', '5G/4G上网', NULL, 100, 1),
('router', 'jd', 'category_lv2', 'equals', '数通网络设备', NULL, 100, 1),
('router', 'jd', 'category_lv2', 'equals', '网络盒子', NULL, 100, 1),

-- ───── 路由器 tmall ─────
('router', 'tmall', 'category_lv2', 'equals', '路由器', NULL, 100, 1),
('router', 'tmall', 'category_lv2', 'equals', '其他网络相关', NULL, 100, 1),
('router', 'tmall', 'category_lv3', 'equals', '智能中控/智能控制面板', NULL, 100, 1),
('router', 'tmall', 'category_lv3', 'equals', '智能插座', NULL, 100, 1),
('router', 'tmall', 'category_lv3', 'equals', '智能家居套装', NULL, 100, 1),

-- ───── 行车记录仪 jd ─────
('dashcam', 'jd', 'category_lv2', 'equals', '行车记录仪', NULL, 100, 1),
('dashcam', 'jd', 'category_lv2', 'equals', '车机导航/车载显示屏车载电器', NULL, 100, 1),
('dashcam', 'jd', 'category_lv2', 'equals', '摩托车记录仪', NULL, 100, 1),
('dashcam', 'jd', 'category_lv2', 'equals', '摩托车蓝牙装备', NULL, 100, 1),

-- ───── 行车记录仪 tmall ─────
('dashcam', 'tmall', 'category_lv3', 'equals', '摩托车行车记录仪', NULL, 100, 1),
('dashcam', 'tmall', 'category_lv2', 'equals', '汽车智能网联', NULL, 100, 1),

-- ───── 移动电源 jd ─────
('power_bank', 'jd', 'category_lv2', 'contains', '移动电源', NULL, 100, 1),

-- ───── 移动电源 tmall ─────
('power_bank', 'tmall', 'category_lv2', 'equals', '便携电源', NULL, 100, 1),
('power_bank', 'tmall', 'category_lv2', 'equals', '3C数码及配件', NULL, 100, 1);
