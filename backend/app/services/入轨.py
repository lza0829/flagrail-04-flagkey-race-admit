import json
from datetime import datetime, timezone

from app.db import 写事务, 连接
from app.modules.开关键竞态准入 import 准入


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 入一批(体: dict) -> dict:
    """一批入轨：整批一个独占写事务，逐版调用竞态准入（同票：版本行+指针+世代）。"""
    批次 = 体.get("批次编号") or f"入轨-{此刻()}"
    版本们 = 体.get("版本") or []
    明细 = []
    with 写事务() as conn:
        准入数 = 幂等数 = 冲突数 = 0
        for v in 版本们:
            结果 = 准入(conn, v)
            明细.append(结果)
            if 结果["结果"] == "准入":
                准入数 += 1
            elif 结果["结果"] == "幂等":
                幂等数 += 1
            else:
                冲突数 += 1
        报告 = {
            "类型": "入轨",
            "准入": 准入数,
            "幂等": 幂等数,
            "冲突": 冲突数,
            "明细": 明细,
        }
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
    return {"批次编号": 批次, "报告": 报告}
