-- ====================================================
-- 一次性修复脚本（幂等版）：补齐 P7-P11 所有缺失变更
-- 可重复执行，已存在的结构会跳过
-- ====================================================

DROP PROCEDURE IF EXISTS fix_migrations;
DELIMITER $$
CREATE PROCEDURE fix_migrations()
BEGIN

-- P7: noise_words.category_code
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='noise_words' AND COLUMN_NAME='category_code'
) THEN
    ALTER TABLE noise_words ADD COLUMN category_code VARCHAR(50) NULL;
    CREATE INDEX ix_noise_words_category_code ON noise_words(category_code);
END IF;

-- P8: dispatch_rules
CREATE TABLE IF NOT EXISTS dispatch_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    platform VARCHAR(50) NULL,
    field VARCHAR(50) NOT NULL,
    match_type VARCHAR(20) NOT NULL,
    value VARCHAR(200) NOT NULL,
    item_name_keyword VARCHAR(200) NULL,
    priority INT NOT NULL DEFAULT 100,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_dispatch_rules_category_code (category_code),
    INDEX ix_dispatch_rules_priority (priority)
);

-- P8: dispatch_batches
CREATE TABLE IF NOT EXISTS dispatch_batches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    file_id INT NULL,
    category_code VARCHAR(50) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    total_rows INT NULL,
    dispatched_rows INT NULL,
    unmatched_rows INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    CONSTRAINT fk_db_file FOREIGN KEY (file_id) REFERENCES upload_files(id) ON DELETE SET NULL,
    INDEX ix_dispatch_batches_file_id (file_id)
);

-- P8: dispatch_items
CREATE TABLE IF NOT EXISTS dispatch_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    raw_data_id INT NULL,
    category_code VARCHAR(50) NOT NULL,
    matched_rule_id INT NULL,
    UNIQUE KEY uq_dispatch_items_batch_row_category (batch_id, raw_data_id, category_code),
    CONSTRAINT fk_di_batch FOREIGN KEY (batch_id) REFERENCES dispatch_batches(id) ON DELETE CASCADE,
    CONSTRAINT fk_di_raw FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE SET NULL,
    INDEX ix_dispatch_items_batch_id (batch_id),
    INDEX ix_dispatch_items_category_code (category_code)
);

-- P8: clean_jobs.dispatch_batch_id
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clean_jobs' AND COLUMN_NAME='dispatch_batch_id'
) THEN
    ALTER TABLE clean_jobs ADD COLUMN dispatch_batch_id INT NULL;
END IF;

-- P8: clean_jobs.dispatch_category_code
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clean_jobs' AND COLUMN_NAME='dispatch_category_code'
) THEN
    ALTER TABLE clean_jobs ADD COLUMN dispatch_category_code VARCHAR(50) NULL;
END IF;

-- P9: column_templates
CREATE TABLE IF NOT EXISTS column_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    platform VARCHAR(50) NULL,
    col_fingerprint VARCHAR(32) NULL,
    mapping JSON NOT NULL,
    ignore_columns JSON NULL,
    is_builtin SMALLINT NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_template_name (name)
);

-- P9: upload_files.template_id
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='upload_files' AND COLUMN_NAME='template_id'
) THEN
    ALTER TABLE upload_files ADD COLUMN template_id INT NULL;
END IF;

-- P9: raw_data.extra_data
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND COLUMN_NAME='extra_data'
) THEN
    ALTER TABLE raw_data ADD COLUMN extra_data JSON NULL;
END IF;

-- P9: 内置模板
INSERT IGNORE INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin)
VALUES ('京东月报', 'jd', '3d069be5456862306693a0bbd0e4ef02', '{"平台": "platform", "月": "month", "Lv0类目名称(逐月固定)": "category_lv0", "Lv1类目名称(逐月固定)": "category_lv1", "Lv2类目名称(逐月固定)": "category_lv2", "宝贝ID": "item_id", "宝贝名称": "item_name", "宝贝图片": "item_image", "宝贝链接": "item_url", "参考价格": "ref_price", "宝贝品牌(bid)": "brand_raw", "宝贝店铺名称": "shop_name", "销量": "sales_qty", "销售额": "sales_amount", "价格": "price", "品牌": "brand_std", "机型": "model_std"}', '[]', 1);
INSERT IGNORE INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin)
VALUES ('天猫/淘宝月报', 'tmall', 'fdabfb884f2174837ba33176dcdf7795', '{"平台": "platform", "月": "month", "Lv1类目名称(逐月固定)": "category_lv1", "Lv2类目名称(逐月固定)": "category_lv2", "Lv3类目名称(逐月固定)": "category_lv3", "Lv4类目名称(逐月固定)": "category_lv4", "Lv5类目名称(逐月固定)": "category_lv5", "宝贝ID": "item_id", "宝贝名称": "item_name", "宝贝图片": "item_image", "宝贝链接": "item_url", "参考价格": "ref_price", "宝贝品牌": "brand_raw", "宝贝店铺名称": "shop_name", "销量": "sales_qty", "销售额": "sales_amount", "价格": "price", "品牌": "brand_std", "机型": "model_std"}', '[]', 1);

-- P10: column_templates.module
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='column_templates' AND COLUMN_NAME='module'
) THEN
    ALTER TABLE column_templates ADD COLUMN module VARCHAR(20) NOT NULL DEFAULT 'sales';
    ALTER TABLE column_templates DROP INDEX uq_template_name;
    CREATE UNIQUE INDEX uq_module_template_name ON column_templates(module, name);
    UPDATE column_templates SET module = 'sales' WHERE is_builtin = 1;
END IF;

-- 更新 alembic 版本
UPDATE alembic_version SET version_num = 'p11a1b2c3d4e5';

END$$
DELIMITER ;

CALL fix_migrations();
DROP PROCEDURE IF EXISTS fix_migrations;

