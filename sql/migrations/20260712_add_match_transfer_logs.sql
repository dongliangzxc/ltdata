-- 20260712: 新增单条转移审计日志表
CREATE TABLE IF NOT EXISTS match_transfer_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  match_result_id BIGINT NOT NULL,
  raw_data_id BIGINT NOT NULL,
  from_clean_job_id INT NOT NULL,
  to_clean_job_id INT NOT NULL,
  operator VARCHAR(100) NULL,
  transferred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mtl_from_job (from_clean_job_id),
  INDEX idx_mtl_to_job (to_clean_job_id),
  INDEX idx_mtl_match_result (match_result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
