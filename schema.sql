CREATE DATABASE IF NOT EXISTS tank
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE tank;

-- 전차 사전용 제원 원본 데이터 (위협도 계산과 무관)
-- 컬럼 1~32는 tank_dictionary.xlsx 와 같은 순서·이름
CREATE TABLE IF NOT EXISTS tank_specs (
    tank_id              VARCHAR(32)   NOT NULL PRIMARY KEY,  -- TANK_0001 형식
    canonical_name       VARCHAR(100)  NOT NULL,
    aliases              VARCHAR(255),                 -- ' | ' 로 구분
    family_name          VARCHAR(100),
    variant_name         VARCHAR(100),                 -- 단일 모델은 'Base'
    tank_type            VARCHAR(100),                 -- 쉼표로 여러 개 가능
    generation           VARCHAR(100),                 -- 쉼표로 여러 개 가능
    origin_country       VARCHAR(50),
    manufacturer         VARCHAR(255),
    service_year         VARCHAR(255),                 -- '1998', '2009~2014년', '1945 for M26 1949 for M46' 등
    operator_countries   VARCHAR(255),                 -- 쉼표 또는 ' | ' 로 구분
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
    era                  VARCHAR(100),                 -- 0(없음) 또는 장비명
    aps                  VARCHAR(255),                 -- '없음' 또는 ' | ' 로 구분된 방식 목록
    defense_systems      VARCHAR(255),                 -- ' | ' 로 구분
    engine               VARCHAR(255),
    engine_power_hp      INT,
    power_to_weight_hp_t DECIMAL(6, 2),
    max_road_speed_kmh   DECIMAL(5, 1),
    range_km             INT,
    sources              VARCHAR(255),                 -- ' | ' 로 구분 (Namuwiki, Wikipedia, ...)
    source_count         TINYINT,
    -- 엑셀에 없음, 화면(dictionary.py)이 읽는 컬럼이라 NULL 허용으로 유지
    spec_count           INT,
    `spec_coverage_%`    DECIMAL(5, 1)                 -- 0~100
) DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
