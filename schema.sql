CREATE DATABASE IF NOT EXISTS tank
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE tank;

-- 전차 사전용 제원 원본 데이터 (위협도 계산과 무관)
CREATE TABLE IF NOT EXISTS tank_specs (
    tank_id              VARCHAR(32)   NOT NULL PRIMARY KEY,
    canonical_name       VARCHAR(100)  NOT NULL,
    aliases              VARCHAR(255),                 -- 쉼표로 구분
    family_name          VARCHAR(100),
    variant_name         VARCHAR(100),
    tank_type            VARCHAR(50),
    generation           VARCHAR(50),
    origin_country       VARCHAR(50),
    manufacturer         VARCHAR(255),
    service_year         SMALLINT,
    operator_countries   VARCHAR(255),                 -- 쉼표로 구분
    crew                 TINYINT,
    combat_weight_t      DECIMAL(6, 2),
    length_m             DECIMAL(5, 2),
    width_m              DECIMAL(5, 2),
    height_m             DECIMAL(5, 2),
    main_gun             VARCHAR(255),
    main_gun_caliber_mm  DECIMAL(5, 1),
    main_ammunition      VARCHAR(255),
    effective_range_m    INT,
    secondary_weapons    VARCHAR(255),
    armor_description    TEXT,
    era                  VARCHAR(100),                 -- Y/N 또는 장비명
    aps                  VARCHAR(100),                 -- Y/N 또는 장비명
    defense_systems      VARCHAR(255),
    engine               VARCHAR(255),
    engine_power_hp      INT,
    power_to_weight_hp_t DECIMAL(5, 1),
    max_road_speed_kmh   DECIMAL(5, 1),
    range_km             INT,
    sources              TEXT,
    source_count         INT,
    spec_count           INT,
    `spec_coverage_%`    DECIMAL(5, 1)                 -- 0~100
) DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- 화면 확인용 예시 데이터 (검증 전 임의 값)
INSERT IGNORE INTO tank_specs VALUES (
    'KR-K2-001', 'K2 흑표', '흑표, Black Panther, K2 Black Panther', 'K2', 'K2', 'MBT', '3.5세대',
    '대한민국', '현대로템', 2014, '대한민국, 폴란드',
    3, 55.0, 10.80, 3.60, 2.40,
    'CN08 120mm 55구경장 활강포', 120.0, 'K279 날개안정분리철갑탄, KSTAM 자탄', 3000,
    '12.7mm K6 중기관총, 7.62mm 동축기관총',
    '모듈식 복합장갑', 'N', 'Y', '레이저 경보장치, 연막탄 발사기',
    'DV27K 디젤 엔진', 1500, 27.3, 70.0, 450,
    '예시 데이터 (출처 검증 전)', 1, 33, 97.0
);
