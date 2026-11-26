import json
from datetime import datetime, timezone

from app.db import 写事务, 连接
from fastapi import HTTPException


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _下一票(conn, 体: dict) -> dict:
    """在既有独占写事务内下单。下发与读指针同事务，读不到空版本。

    甲口径：必须钉当前版本键。非当前版（哪怕已入轨、状态合法）一律失败闭。
    """
    版本键 = 体["版本键"]
    桶键 = 体["桶键"]
    票号 = 体.get("票号") or f"票-{版本键}-{桶键}"

    ver = conn.execute("SELECT * FROM 开关版本 WHERE 版本键=?", (版本键,)).fetchone()
    if not ver:
        raise HTTPException(400, f"版本未入轨:{版本键}")
    if ver["状态"] not in ("已入轨", "灰度中"):
        raise HTTPException(400, f"版本状态不可下发:{ver['状态']}")

    指针 = conn.execute(
        "SELECT * FROM 当前版本 WHERE 开关键=?", (ver["开关键"],)
    ).fetchone()
    if not 指针:
        raise HTTPException(409, f"开关键无当前版本，拒绝钉空版本:{ver['开关键']}")
    if 指针["版本键"] != 版本键:
        raise HTTPException(
            409,
            f"非当前版本不可下发:{版本键}；当前须钉:{指针['版本键']}",
        )

    bucket = conn.execute(
        "SELECT * FROM 分桶规 WHERE 桶键=? AND 状态='生效'", (桶键,)
    ).fetchone()
    if not bucket:
        raise HTTPException(400, f"分桶未生效:{桶键}")
    if bucket["开关键"] != ver["开关键"]:
        raise HTTPException(400, "分桶开关键与版本不一致")

    已 = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
    if 已 and 已["状态"] == "已下发":
        return {"票号": 票号, "状态": "已下发", "幂等": True,
                "版本键": 已["版本键"], "世代": int(已["世代"]), "钉版": 已["钉版"]}

    世代 = int(指针["世代"])
    conn.execute(
        """INSERT INTO 下发票(票号, 开关键, 版本键, 桶键, 状态, 下发时, 世代, 钉版, 说明)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(票号) DO UPDATE SET
             状态='已下发', 下发时=excluded.下发时,
             世代=excluded.世代, 钉版=excluded.钉版""",
        (票号, ver["开关键"], 版本键, 桶键, "已下发", 此刻(), 世代,
         指针["版本键"], 体.get("说明", "")),
    )
    conn.execute("UPDATE 开关版本 SET 状态='灰度中' WHERE 版本键=?", (版本键,))
    return {"票号": 票号, "状态": "已下发", "幂等": False,
            "版本键": 版本键, "世代": 世代, "钉版": 指针["版本键"]}


def 下一票(体: dict) -> dict:
    with 写事务() as conn:
        return _下一票(conn, 体)


def 装下发夹具(体: dict) -> dict:
    批次 = 体.get("批次编号") or f"下发-{此刻()}"
    结果 = []
    with 写事务() as conn:
        for item in 体.get("下发") or []:
            结果.append(_下一票(conn, item))
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps({"类型": "下发", "结果": 结果}, ensure_ascii=False)),
        )
    return {"批次编号": 批次, "报告": {"类型": "下发", "结果": 结果}}
