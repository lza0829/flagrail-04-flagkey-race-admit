from app.db import 连接
from app.modules.开关键竞态准入 import 核证


def 总览() -> dict:
    conn = 连接()
    try:
        def c(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        核 = 核证(conn)
        return {
            "开关版本": c("SELECT COUNT(*) FROM 开关版本"),
            "分桶规": c("SELECT COUNT(*) FROM 分桶规 WHERE 状态='生效'"),
            "下发票": c("SELECT COUNT(*) FROM 下发票"),
            "已下发": c("SELECT COUNT(*) FROM 下发票 WHERE 状态='已下发'"),
            "回读证": c("SELECT COUNT(*) FROM 回读证"),
            "确认回读": c("SELECT COUNT(*) FROM 回读证 WHERE 结果='确认'"),
            "命运条": c("SELECT COUNT(*) FROM 命运账"),
            "冲突单": c("SELECT COUNT(*) FROM 冲突单"),
            "准入架构": 核["架构"],
            "准入有效": 核["有效"],
            "最近贯验通过": bool(
                (conn.execute(
                    "SELECT 是否通过 FROM 轨贯验 ORDER BY 编号 DESC LIMIT 1"
                ).fetchone() or [0])[0]
            ),
        }
    finally:
        conn.close()
