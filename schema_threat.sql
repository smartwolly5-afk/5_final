-- 위협도·대응수준 테이블 (MySQL 기준). 데모 모드(SQLite)는 threat_db.init_schema()가 방언만 바꿔 적용한다.
-- 적용: python sync_threat_db.py  (테이블 생성 → 계수 seed → 전체 재계산)

-- 기준값·판정 경계값 (key/value). 경계값을 바꾸면 대응수준 판정이 바로 바뀐다
CREATE TABLE IF NOT EXISTS threat_coef (
    k     VARCHAR(32)  NOT NULL PRIMARY KEY,   -- cal, len, pw, h, hmin, hmax, lv1, lv2, lv3, floor_t
    v     DOUBLE       NOT NULL,
    note  VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS ammo_coef (
    ammo  VARCHAR(32)  NOT NULL PRIMARY KEY,   -- APFSDS, 포발사 ATGM, HEAT, ...
    coef  DOUBLE       NOT NULL
);

CREATE TABLE IF NOT EXISTS gen_coef (
    gen   VARCHAR(16)  NOT NULL PRIMARY KEY,   -- 3.5세대, 3세대, 2세대, 1세대, 구형/미상
    coef  DOUBLE       NOT NULL
);

CREATE TABLE IF NOT EXISTS tactic_weight (
    tactic_no     TINYINT      NOT NULL PRIMARY KEY,   -- 1~11
    name          VARCHAR(32)  NOT NULL,
    w_f           DOUBLE,
    w_m           DOUBLE,
    w_p           DOUBLE,
    tank_allowed  TINYINT      NOT NULL DEFAULT 1      -- 11번(전투근무지원)은 화력 0이라 전차 불가
);

-- 기종별 위협도 (sync_threat_db.py 가 tank_specs 로부터 전체 재계산)
CREATE TABLE IF NOT EXISTS tank_threat (
    tank_id         VARCHAR(32)  NOT NULL PRIMARY KEY,
    canonical_name  VARCHAR(100),
    family_name     VARCHAR(100),
    type_group      VARCHAR(16),     -- 주력전차, 중전차, 중형전차, 경전차, 순항전차, 보병전차, 초중전차, 미상
    computable      TINYINT,         -- 0이면 구경 결측으로 T 없음
    confidence      VARCHAR(4),      -- 상 / 중 / 하
    cal_mm          DOUBLE,
    cal_len         DOUBLE,
    ammo            VARCHAR(32),
    gen             VARCHAR(16),
    pw              DOUBLE,
    armor           DOUBLE,
    height          DOUBLE,
    cal_src         VARCHAR(64),
    len_src         VARCHAR(64),
    ammo_src        VARCHAR(64),
    gen_src         VARCHAR(64),
    pw_src          VARCHAR(64),
    armor_src       VARCHAR(64),
    height_src      VARCHAR(64),
    armor_rule      VARCHAR(128),
    era_ref         TINYINT,         -- 참고용, 식에는 미반영
    era_src         VARCHAR(64),
    f DOUBLE, m DOUBLE, p DOUBLE,
    t1 DOUBLE, t2 DOUBLE, t3 DOUBLE, t4 DOUBLE, t5 DOUBLE,
    t6 DOUBLE, t7 DOUBLE, t8 DOUBLE, t9 DOUBLE, t10 DOUBLE,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- 유형별 T 요약 (전술별). t_p75 = True Unknown 대체값
CREATE TABLE IF NOT EXISTS type_threat_summary (
    type_group  VARCHAR(16)  NOT NULL,
    tactic_no   TINYINT      NOT NULL,
    n           INT,
    t_median    DOUBLE,
    t_p75       DOUBLE,
    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (type_group, tactic_no)
);

-- 군집 판정 기록 (가장 최근 행이 그 군집의 현재 상태, input_json 으로 재판정)
CREATE TABLE IF NOT EXISTS cluster_assessment (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    cluster_id   VARCHAR(64)  NOT NULL,
    level        TINYINT,
    score        DOUBLE,
    t_cluster    DOUBLE,
    echelon_e    TINYINT,
    n_vehicles   INT,
    tactic_no    TINYINT,
    input_json   TEXT,
    result_json  TEXT,
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- 지휘관 수정 이력
CREATE TABLE IF NOT EXISTS commander_override (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    cluster_id    VARCHAR(64)  NOT NULL,
    actor         VARCHAR(64),
    item          VARCHAR(16)  NOT NULL,   -- tactic | core_target
    before_value  VARCHAR(255),
    after_value   VARCHAR(255),
    level_before  TINYINT,
    level_after   TINYINT,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- ───────── Unknown 레지스트리 (dashboard/unknown_registry.py) ─────────
-- 미확인 그룹: 같은 미확인 '기종'으로 보이는 표적 묶음 (같은 '개체'가 아님). 영상이 달라도 임베딩이 비슷하면 한 그룹
CREATE TABLE IF NOT EXISTS unknown_group (
    group_id           VARCHAR(32)  NOT NULL PRIMARY KEY,   -- UNK-G0001
    status             VARCHAR(16)  NOT NULL DEFAULT 'open', -- open | confirmed | merged | dismissed
    family_guess       VARCHAR(100),
    type_group         VARCHAR(16),
    centroid           TEXT,                                -- 평균 임베딩 (JSON 리스트)
    n_tracks           INT DEFAULT 0,                       -- 고유 트랙 수 (프레임 수 아님)
    n_videos           INT DEFAULT 0,                       -- 고유 영상 수
    max_threat         DOUBLE,
    threat_source      VARCHAR(64),                         -- 위협도 근거 문장 (계열·유형 상위값 등)
    has_cope_cage      TINYINT DEFAULT 0,
    commander_seen     TINYINT DEFAULT 0,
    priority           DOUBLE,                              -- 순위 점수 (저장 시점 값, 목록은 다시 계산)
    review_candidates  TEXT,                                -- 병합 후보 [{"group_id", "similarity"}] (GROUP_SIM_REVIEW 이상)
    confirmed_tank_id  VARCHAR(32),
    merged_into        VARCHAR(32),
    first_seen         DATETIME,
    last_seen          DATETIME,
    updated_at         DATETIME
);

-- 출현 기록: 트랙 1개 = 1행. 같은 영상을 다시 분석해도 (video, tracking_id) 로 한 행만 남는다
CREATE TABLE IF NOT EXISTS unknown_sighting (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    group_id     VARCHAR(32),
    video        VARCHAR(255),
    tracking_id  VARCHAR(64),
    cluster_id   VARCHAR(64),
    similarity   DOUBLE,                                    -- 들어갈 때 그룹 centroid 와의 유사도 (새 그룹이면 NULL)
    top_k_json   TEXT,
    embedding    TEXT,
    threat       DOUBLE,
    lat          DOUBLE,
    lon          DOUBLE,
    captured_at  DATETIME,
    created_at   DATETIME,
    UNIQUE (video, tracking_id)
);

CREATE TABLE IF NOT EXISTS unknown_crop (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    sighting_id  BIGINT,
    group_id     VARCHAR(32),
    path         VARCHAR(255),                              -- static 기준 경로 (unknown_crops/<group>/<video>_<track>_<frame>.jpg)
    quality      DOUBLE,
    frame_idx    INT,
    created_at   DATETIME
);

-- 분석관 조치 이력 (확정·병합·분리·기각)
CREATE TABLE IF NOT EXISTS unknown_action (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    group_id    VARCHAR(32),
    actor       VARCHAR(64),
    action      VARCHAR(16),
    detail      TEXT,
    created_at  DATETIME
);
