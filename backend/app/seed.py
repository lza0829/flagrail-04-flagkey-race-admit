from datetime import datetime, timezone

from app.db import 连接, 写事务

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 开关版本 (
  版本键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本号 INTEGER NOT NULL,
  载荷 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '已入轨',
  入轨时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT '',
  世代 INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_开关版本_键 ON 开关版本(开关键);
CREATE TABLE IF NOT EXISTS 当前版本 (
  开关键 TEXT PRIMARY KEY,
  版本键 TEXT NOT NULL,
  世代 INTEGER NOT NULL,
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 冲突单 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  开关键 TEXT NOT NULL,
  被拒版本键 TEXT NOT NULL,
  现行版本键 TEXT NOT NULL DEFAULT '',
  现行世代 INTEGER NOT NULL DEFAULT 0,
  提议世代 INTEGER NOT NULL DEFAULT 0,
  载荷 TEXT NOT NULL DEFAULT '',
  原因 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_冲突单_键 ON 冲突单(开关键);
CREATE TABLE IF NOT EXISTS 分桶规 (
  桶键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  桶类型 TEXT NOT NULL,
  规则 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '生效',
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 下发票 (
  票号 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本键 TEXT NOT NULL,
  桶键 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '待下发',
  下发时 TEXT NOT NULL DEFAULT '',
  世代 INTEGER NOT NULL DEFAULT 1,
  钉版 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 回读证 (
  证号 TEXT PRIMARY KEY,
  票号 TEXT NOT NULL,
  边缘键 TEXT NOT NULL,
  所见版本键 TEXT NOT NULL DEFAULT '',
  结果 TEXT NOT NULL,
  回读时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 命运账 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  对象类型 TEXT NOT NULL,
  对象键 TEXT NOT NULL,
  命运 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 轨贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  版本数 INTEGER NOT NULL,
  下发数 INTEGER NOT NULL,
  回读数 INTEGER NOT NULL,
  命运数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 空桩 (
  名 TEXT PRIMARY KEY,
  状态 TEXT NOT NULL DEFAULT '空桩'
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _列名(conn, 表: str) -> set:
    return {r[1] for r in conn.execute('PRAGMA table_info("%s")' % 表)}


def _迁移(conn) -> None:
    """兼容既有库：补列、补世代、回填当前指针（不改写已有载荷/状态）。"""
    if "世代" not in _列名(conn, "开关版本"):
        conn.execute("ALTER TABLE 开关版本 ADD COLUMN 世代 INTEGER NOT NULL DEFAULT 0")
    if "钉版" not in _列名(conn, "下发票"):
        conn.execute("ALTER TABLE 下发票 ADD COLUMN 钉版 TEXT NOT NULL DEFAULT ''")

    # 世代 <= 0 的旧行：按开关键、入轨时顺序补 1..n。
    for r in conn.execute(
        "SELECT DISTINCT 开关键 FROM 开关版本 WHERE 世代<=0"
    ).fetchall():
        键 = r["开关键"]
        旧 = conn.execute(
            "SELECT 版本键 FROM 开关版本 WHERE 开关键=? AND 世代<=0 ORDER BY 入轨时, 版本键",
            (键,),
        ).fetchall()
        起 = conn.execute(
            "SELECT COALESCE(MAX(世代),0) FROM 开关版本 WHERE 开关键=?", (键,)
        ).fetchone()[0]
        for i, x in enumerate(旧, start=1):
            conn.execute(
                "UPDATE 开关版本 SET 世代=? WHERE 版本键=?", (起 + i, x["版本键"])
            )

    # 回填当前指针：仅当该键恰有一个活跃版本且尚无指针。
    for r in conn.execute(
        "SELECT DISTINCT 开关键 FROM 开关版本 WHERE 状态 IN ('已入轨','灰度中')"
    ).fetchall():
        键 = r["开关键"]
        if conn.execute("SELECT 1 FROM 当前版本 WHERE 开关键=?", (键,)).fetchone():
            continue
        活跃 = conn.execute(
            "SELECT 版本键, 世代 FROM 开关版本 WHERE 开关键=? AND 状态 IN ('已入轨','灰度中')",
            (键,),
        ).fetchall()
        if len(活跃) == 1:
            conn.execute(
                "INSERT INTO 当前版本(开关键, 版本键, 世代, 更新时) VALUES (?,?,?,?)",
                (键, 活跃[0]["版本键"], int(活跃[0]["世代"] or 0), 此刻()),
            )


def 初始化库() -> None:
    conn = 连接()
    try:
        conn.executescript(建表)
        conn.commit()
    finally:
        conn.close()

    with 写事务() as conn:
        _迁移(conn)
        if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
            for k, v in {
                "站名": "灰度轨",
                "领域": "基础设施",
                "子方向": "中间件",
                "默认灰度比": "10",
                "回读齐套策略": "全边缘确认才可晋升",
                "骨架": "开关版本入轨→分桶灰度下发→回读确认→失效/回滚互证",
                "准入架构": "甲:单胜出",
                "入轨口径": "同开关键仅一版已入轨且当前唯一；冲突方入轨失败并留冲突单；下发必须钉当前版本键",
            }.items():
                conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))
        else:
            conn.execute(
                "INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)",
                ("准入架构", "甲:单胜出"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)",
                ("入轨口径", "同开关键仅一版已入轨且当前唯一；冲突方入轨失败并留冲突单；下发必须钉当前版本键"),
            )
        for name in [
            "分桶比例冲突", "名单与百分比互斥", "回读超时旁置", "半截下发回滚",
            "双版本同键并发", "回读偏差拒升全量", "环境桶隔离", "失效后幽灵回读",
            "下发票幂等键", "回滚窗互斥", "变体载荷契约", "边缘时钟漂移",
            "分桶重切", "全量晋升闸", "影子轨对照", "配置世代戳",
            "回读仲裁策略", "失效写闸", "跨环境串扰", "轨贯验三联",
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO 空桩(名, 状态) VALUES (?, '空桩')", (name,)
            )
        # 本模块已落地，不再计入空桩。
        conn.execute("DELETE FROM 空桩 WHERE 名='开关键竞态准入'")
