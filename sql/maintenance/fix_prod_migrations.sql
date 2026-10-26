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

-- 分发批次关联上传批次
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatch_batches' AND COLUMN_NAME='batch_key'
) THEN
    ALTER TABLE dispatch_batches ADD COLUMN batch_key VARCHAR(64) NULL;
    CREATE INDEX ix_dispatch_batches_batch_key ON dispatch_batches(batch_key);
END IF;

-- 商品名称翻译缓存
CREATE TABLE IF NOT EXISTS translation_cache (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_hash     CHAR(64)    NOT NULL,
    source_text     TEXT        NULL,
    source_lang     VARCHAR(16) NOT NULL DEFAULT 'auto',
    target_lang     VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
    provider        VARCHAR(32) NOT NULL,
    translated_text TEXT        NOT NULL,
    created_at      DATETIME    DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_translation_cache (source_hash, target_lang, provider),
    KEY idx_translation_cache_hash (source_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品名称翻译缓存';

-- 海外国家与汇率
CREATE TABLE IF NOT EXISTS countries (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    code            VARCHAR(8)   NOT NULL,
    name_cn         VARCHAR(64)  NOT NULL,
    name_en         VARCHAR(128) NULL,
    currency_code   VARCHAR(8)   NOT NULL,
    currency_symbol VARCHAR(8)   NULL,
    region          VARCHAR(16)  NOT NULL DEFAULT 'overseas',
    is_active       TINYINT      NOT NULL DEFAULT 1,
    sort_order      INT          NOT NULL DEFAULT 100,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_countries_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家与币种主数据';

INSERT IGNORE INTO countries
    (code, name_cn, name_en, currency_code, currency_symbol, region, is_active, sort_order)
VALUES
    ('CN', '中国', 'China', 'CNY', '¥', 'domestic', 1, 0),
    ('AE', '阿联酋', 'United Arab Emirates', 'AED', 'AED', 'overseas', 1, 10),
    ('AU', '澳大利亚', 'Australia', 'AUD', 'A$', 'overseas', 1, 20),
    ('BR', '巴西', 'Brazil', 'BRL', 'R$', 'overseas', 1, 30),
    ('CA', '加拿大', 'Canada', 'CAD', 'C$', 'overseas', 1, 40),
    ('DE', '德国', 'Germany', 'EUR', '€', 'overseas', 1, 50),
    ('ES', '西班牙', 'Spain', 'EUR', '€', 'overseas', 1, 60),
    ('FR', '法国', 'France', 'EUR', '€', 'overseas', 1, 70),
    ('GB', '英国', 'United Kingdom', 'GBP', '£', 'overseas', 1, 80),
    ('IN', '印度', 'India', 'INR', '₹', 'overseas', 1, 90),
    ('IT', '意大利', 'Italy', 'EUR', '€', 'overseas', 1, 100),
    ('JP', '日本', 'Japan', 'JPY', '¥', 'overseas', 1, 110),
    ('MX', '墨西哥', 'Mexico', 'MXN', 'MX$', 'overseas', 1, 120),
    ('SA', '沙特阿拉伯', 'Saudi Arabia', 'SAR', 'SAR', 'overseas', 1, 130),
    ('US', '美国', 'United States', 'USD', '$', 'overseas', 1, 140),
    ('ID', '印度尼西亚', 'Indonesia', 'IDR', 'Rp', 'overseas', 1, 150),
    ('MY', '马来西亚', 'Malaysia', 'MYR', 'RM', 'overseas', 1, 160),
    ('PH', '菲律宾', 'Philippines', 'PHP', '₱', 'overseas', 1, 170),
    ('SG', '新加坡', 'Singapore', 'SGD', 'S$', 'overseas', 1, 180),
    ('TH', '泰国', 'Thailand', 'THB', '฿', 'overseas', 1, 190),
    ('TW', '中国台湾', 'Taiwan, China', 'TWD', 'NT$', 'overseas', 1, 200),
    ('VN', '越南', 'Vietnam', 'VND', '₫', 'overseas', 1, 210);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    country_code  VARCHAR(8)    NOT NULL,
    currency_code VARCHAR(8)    NOT NULL,
    rate_to_cny   DECIMAL(18,8) NOT NULL,
    source        VARCHAR(32)   NOT NULL DEFAULT 'manual',
    operator      VARCHAR(100)  NULL,
    remark        VARCHAR(500)  NULL,
    created_at    DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fx_country (country_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家兑人民币汇率';

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='upload_files' AND COLUMN_NAME='batch_key'
) THEN
    ALTER TABLE upload_files ADD COLUMN batch_key VARCHAR(64) NULL;
    CREATE INDEX ix_upload_files_batch_key ON upload_files(batch_key);
END IF;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='upload_files' AND COLUMN_NAME='country_code'
) THEN
    ALTER TABLE upload_files ADD COLUMN country_code VARCHAR(8) NULL;
    CREATE INDEX ix_upload_files_country_code ON upload_files(country_code);
END IF;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND COLUMN_NAME='source_category_code'
) THEN
    ALTER TABLE raw_data ADD COLUMN source_category_code VARCHAR(50) NULL;
    CREATE INDEX ix_raw_data_source_category_code ON raw_data(source_category_code);
END IF;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND COLUMN_NAME='source_category_name'
) THEN
    ALTER TABLE raw_data ADD COLUMN source_category_name VARCHAR(200) NULL;
END IF;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND COLUMN_NAME='country_code'
) THEN
    ALTER TABLE raw_data ADD COLUMN country_code VARCHAR(8) NULL;
    CREATE INDEX ix_raw_data_country_code ON raw_data(country_code);
END IF;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cleaned_data' AND COLUMN_NAME='country_code'
) THEN
    ALTER TABLE cleaned_data ADD COLUMN country_code VARCHAR(8) NULL;
    CREATE INDEX ix_cleaned_data_country_code ON cleaned_data(country_code);
END IF;

UPDATE upload_files SET country_code='CN'
WHERE country_code IS NULL AND (data_region IS NULL OR data_region='domestic');

UPDATE raw_data rd JOIN upload_files uf ON uf.id = rd.file_id
SET rd.country_code='CN'
WHERE rd.country_code IS NULL AND (uf.data_region IS NULL OR uf.data_region='domestic');

UPDATE cleaned_data cd JOIN raw_data rd ON rd.id = cd.raw_data_id
SET cd.country_code=rd.country_code WHERE cd.country_code IS NULL;

-- 原始数据去重键加入国家（重建索引）
IF EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND INDEX_NAME='uq_raw_dedup'
      AND SEQ_IN_INDEX=1 AND COLUMN_NAME='item_id'
) THEN
    ALTER TABLE raw_data DROP INDEX uq_raw_dedup;
    ALTER TABLE raw_data ADD UNIQUE KEY uq_raw_dedup (country_code, item_id, month, platform);
END IF;

IF EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='raw_data' AND INDEX_NAME='idx_raw_dedup_lookup'
      AND SEQ_IN_INDEX=1 AND COLUMN_NAME='item_id'
) THEN
    ALTER TABLE raw_data DROP INDEX idx_raw_dedup_lookup;
    ALTER TABLE raw_data ADD KEY idx_raw_dedup_lookup (country_code, item_id, month, platform);
END IF;

-- 更新 alembic 版本
UPDATE alembic_version SET version_num = 'p11a1b2c3d4e5';

END$$
DELIMITER ;

CALL fix_migrations();
DROP PROCEDURE IF EXISTS fix_migrations;

