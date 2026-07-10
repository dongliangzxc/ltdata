-- ====================================================
-- 全量修复脚本（幂等）：对齐生产库与代码最新结构
-- 可重复执行，已存在的列/表/索引会跳过
-- ====================================================

DROP PROCEDURE IF EXISTS fix_all;
DELIMITER $$
CREATE PROCEDURE fix_all()
BEGIN


IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaned_data' AND COLUMN_NAME='category_lv0') THEN
    ALTER TABLE `cleaned_data` ADD COLUMN category_lv0 VARCHAR(100) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaned_data' AND COLUMN_NAME='calc_price') THEN
    ALTER TABLE `cleaned_data` ADD COLUMN calc_price DECIMAL(12,2) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaned_data' AND COLUMN_NAME='corrected_sales_qty') THEN
    ALTER TABLE `cleaned_data` ADD COLUMN corrected_sales_qty INT NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaned_data' AND COLUMN_NAME='corrected_sales_amount') THEN
    ALTER TABLE `cleaned_data` ADD COLUMN corrected_sales_amount DECIMAL(14,2) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND COLUMN_NAME='extra_data') THEN
    ALTER TABLE `raw_data` ADD COLUMN extra_data JSON NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='noise_words' AND COLUMN_NAME='category_code') THEN
    ALTER TABLE `noise_words` ADD COLUMN category_code VARCHAR(50) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='noise_words' AND INDEX_NAME='ix_noise_words_category_code') THEN
    CREATE INDEX ix_noise_words_category_code ON noise_words(category_code);
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='match_results' AND COLUMN_NAME='match_source') THEN
    ALTER TABLE `match_results` ADD COLUMN match_source VARCHAR(20) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='match_results' AND COLUMN_NAME='is_disabled') THEN
    ALTER TABLE `match_results` ADD COLUMN is_disabled TINYINT(1) NOT NULL DEFAULT 0;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='match_results' AND COLUMN_NAME='disabled_reason') THEN
    ALTER TABLE `match_results` ADD COLUMN disabled_reason VARCHAR(200) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='match_results' AND COLUMN_NAME='disabled_at') THEN
    ALTER TABLE `match_results` ADD COLUMN disabled_at DATETIME NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clean_jobs' AND COLUMN_NAME='dispatch_batch_id') THEN
    ALTER TABLE `clean_jobs` ADD COLUMN dispatch_batch_id INT NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='clean_jobs' AND COLUMN_NAME='dispatch_category_code') THEN
    ALTER TABLE `clean_jobs` ADD COLUMN dispatch_category_code VARCHAR(50) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='upload_files' AND COLUMN_NAME='template_id') THEN
    ALTER TABLE `upload_files` ADD COLUMN template_id INT NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='models' AND COLUMN_NAME='category_code') THEN
    ALTER TABLE `models` ADD COLUMN category_code VARCHAR(50) NULL;
END IF;

CREATE TABLE IF NOT EXISTS match_result_candidates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    match_result_id INT NOT NULL,
    model_id INT NOT NULL,
    model_code VARCHAR(100) NULL,
    brand_code VARCHAR(100) NULL,
    match_source VARCHAR(20) NULL,
    score DECIMAL(5,4) NULL,
    `rank` INT NULL,
    INDEX ix_mrc_match_result (match_result_id),
    CONSTRAINT fk_mrc_match_result FOREIGN KEY (match_result_id) REFERENCES match_results(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_aliases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_id INT NOT NULL,
    alias_code VARCHAR(100) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_model_alias (alias_code),
    CONSTRAINT fk_alias_model FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS correction_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_code VARCHAR(50) NULL,
    platform VARCHAR(50) NULL,
    field VARCHAR(50) NOT NULL,
    match_type VARCHAR(20) NOT NULL,
    match_value VARCHAR(200) NOT NULL,
    action VARCHAR(20) NOT NULL,
    target_field VARCHAR(50) NULL,
    target_value VARCHAR(200) NULL,
    priority INT NOT NULL DEFAULT 100,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_category_code (code)
);

CREATE TABLE IF NOT EXISTS item_url_mappings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    item_id VARCHAR(100) NOT NULL,
    model_id INT NOT NULL,
    price DECIMAL(12,2) NULL,
    item_url TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_url_mapping (platform, item_id)
);

CREATE TABLE IF NOT EXISTS historical_mappings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    item_id VARCHAR(100) NOT NULL,
    model_id INT NOT NULL,
    import_batch VARCHAR(100) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_historical (platform, item_id),
    INDEX ix_historical_import_batch (import_batch)
);

CREATE TABLE IF NOT EXISTS attr_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(200) NOT NULL,
    match_type VARCHAR(20) NOT NULL,
    attr_name VARCHAR(100) NOT NULL,
    attr_value VARCHAR(200) NOT NULL,
    category_code VARCHAR(100) NULL,
    priority INT NOT NULL DEFAULT 100,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_attr_rule (keyword, attr_name, category_code),
    INDEX idx_attr_rules_category (category_code)
);

CREATE TABLE IF NOT EXISTS match_result_attrs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    match_result_id INT NOT NULL,
    attr_name VARCHAR(100) NOT NULL,
    attr_value VARCHAR(200) NOT NULL,
    CONSTRAINT fk_mrc_match_result2 FOREIGN KEY (match_result_id) REFERENCES match_results(id) ON DELETE CASCADE
);

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

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='column_templates' AND COLUMN_NAME='module') THEN
    ALTER TABLE `column_templates` ADD COLUMN module VARCHAR(20) NOT NULL DEFAULT 'sales';
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='column_templates' AND INDEX_NAME='uq_module_template_name') THEN
    ALTER TABLE column_templates DROP INDEX uq_template_name;
    CREATE UNIQUE INDEX uq_module_template_name ON column_templates(module, name);
END IF;

INSERT IGNORE INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin, module)
VALUES ('京东月报', 'jd', '3d069be5456862306693a0bbd0e4ef02', '{"平台": "platform", "月": "month", "Lv0类目名称(逐月固定)": "category_lv0", "Lv1类目名称(逐月固定)": "category_lv1", "Lv2类目名称(逐月固定)": "category_lv2", "宝贝ID": "item_id", "宝贝名称": "item_name", "宝贝图片": "item_image", "宝贝链接": "item_url", "参考价格": "ref_price", "宝贝品牌(bid)": "brand_raw", "宝贝店铺名称": "shop_name", "销量": "sales_qty", "销售额": "sales_amount", "价格": "price", "品牌": "brand_std", "机型": "model_std"}', '[]', 1, 'sales');
INSERT IGNORE INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin, module)
VALUES ('天猫/淘宝月报', 'tmall', 'fdabfb884f2174837ba33176dcdf7795', '{"平台": "platform", "月": "month", "Lv1类目名称(逐月固定)": "category_lv1", "Lv2类目名称(逐月固定)": "category_lv2", "Lv3类目名称(逐月固定)": "category_lv3", "Lv4类目名称(逐月固定)": "category_lv4", "Lv5类目名称(逐月固定)": "category_lv5", "宝贝ID": "item_id", "宝贝名称": "item_name", "宝贝图片": "item_image", "宝贝链接": "item_url", "参考价格": "ref_price", "宝贝品牌": "brand_raw", "宝贝店铺名称": "shop_name", "销量": "sales_qty", "销售额": "sales_amount", "价格": "price", "品牌": "brand_std", "机型": "model_std"}', '[]', 1, 'sales');
UPDATE column_templates SET module = 'sales' WHERE is_builtin = 1 AND module = '';


END$$
DELIMITER ;

CALL fix_all();
DROP PROCEDURE IF EXISTS fix_all;


-- ====================================================
-- 修复 luotu_analytics.published_items 缺失列
-- ====================================================
DROP PROCEDURE IF EXISTS fix_analytics;
DELIMITER $$
CREATE PROCEDURE fix_analytics()
BEGIN

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND COLUMN_NAME='category_lv0') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD COLUMN category_lv0 VARCHAR(100) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND COLUMN_NAME='category_name') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD COLUMN category_name VARCHAR(200) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND COLUMN_NAME='calc_price') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD COLUMN calc_price DECIMAL(12,2) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND COLUMN_NAME='corrected_sales_qty') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD COLUMN corrected_sales_qty INT NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND COLUMN_NAME='corrected_sales_amount') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD COLUMN corrected_sales_amount DECIMAL(14,2) NULL;
END IF;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA='luotu_analytics' AND TABLE_NAME='published_items' AND INDEX_NAME='ix_published_items_model_code_month') THEN
    ALTER TABLE `luotu_analytics`.`published_items` ADD INDEX ix_published_items_model_code_month (model_code, month);
END IF;

END$$
DELIMITER ;

CALL fix_analytics();
DROP PROCEDURE IF EXISTS fix_analytics;

