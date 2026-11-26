"""开关键竞态准入（架构甲：单胜出）。

口径
====
- 同一开关键任一时刻**仅一版已入轨**，且当前指针唯一。
- 「入轨 + 当前指针 + 世代分配」在同一个 ``BEGIN IMMEDIATE`` 写事务里落定（同票），
  要么三样全成，要么全无——绝不留下半截指针/空世代。
- 并发冲突方**不入库**：写入 `冲突单` 留痕（可查、可审计），不覆盖、不静默丢弃。
- 下发必须钉版（`钉版` = 当前指针版本键）。指针为空或与钉版不符即失败闭，
  入轨与下发交错时后到者排队，永远读不到空版本。

架构乙（世代链并存）不在本实现口径内；核证接口会明确回报 ``架构=甲``。
"""

from datetime import datetime, timezone

状态_活跃 = ("已入轨", "灰度中")
架构 = "甲:单胜出"
口径 = "库内仅一版已入轨，当前唯一；冲突方入轨失败可查；下发必须钉当前版本键"


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _序列化载荷(载荷) -> str:
    import json

    if isinstance(载荷, str):
        return 载荷
    return json.dumps(载荷 if 载荷 is not None else {}, ensure_ascii=False)


def _现行(conn, 开关键: str):
    return conn.execute(
        "SELECT * FROM 当前版本 WHERE 开关键=?", (开关键,)
    ).fetchone()


def _活跃行(conn, 开关键: str, 排除版本键: str = ""):
    if 排除版本键:
        return conn.execute(
            "SELECT * FROM 开关版本 WHERE 开关键=? AND 状态 IN ('已入轨','灰度中') "
            "AND 版本键<>? ORDER BY 世代 DESC",
            (开关键, 排除版本键),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM 开关版本 WHERE 开关键=? AND 状态 IN ('已入轨','灰度中') "
        "ORDER BY 世代 DESC",
        (开关键,),
    ).fetchall()


def 记冲突(conn, 开关键: str, 被拒版本键: str, 现行版本键: str, 现行世代: int,
           提议世代: int, 原因: str, 时刻: str, 载荷: str = "", 说明: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO 冲突单(开关键, 被拒版本键, 现行版本键, 现行世代, 提议世代,
                              载荷, 原因, 时刻, 说明)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (开关键, 被拒版本键, 现行版本键, 现行世代, 提议世代,
         载荷, 原因, 时刻, 说明),
    )
    return int(cur.lastrowid)


def 准入(conn, 条目: dict) -> dict:
    """在既有写事务内尝试准入一版。调用方负责 BEGIN IMMEDIATE / COMMIT。

    返回 ``{版本键, 开关键, 结果, 世代, 当前键, 冲突编号?}``；结果 ∈ 准入/幂等/冲突。
    """
    开关键 = 条目["开关键"]
    版本号 = int(条目["版本号"])
    版本键 = 条目.get("版本键") or f"{开关键}@{版本号}"
    载荷 = _序列化载荷(条目.get("载荷", {}))
    说明 = 条目.get("说明", "")
    时刻 = 此刻()

    # 同版本键精确幂等：已存在即跳过（不覆盖任何已有世代/指针）。
    已 = conn.execute("SELECT * FROM 开关版本 WHERE 版本键=?", (版本键,)).fetchone()
    if 已:
        指针 = _现行(conn, 开关键)
        return {
            "版本键": 版本键, "开关键": 开关键, "结果": "幂等",
            "世代": int(已["世代"] or 0),
            "当前键": 指针["版本键"] if 指针 else "",
        }

    指针 = _现行(conn, 开关键)
    活跃 = _活跃行(conn, 开关键, 排除版本键=版本键)

    # 甲口径：指针在，或仍有活跃已入轨版本 → 本版不许入轨，只留冲突单。
    if 指针 or 活跃:
        现行键 = 指针["版本键"] if 指针 else 活跃[0]["版本键"]
        现行世代 = int(指针["世代"]) if 指针 else int(活跃[0]["世代"] or 0)
        最大世代 = conn.execute(
            "SELECT COALESCE(MAX(世代),0) AS m FROM 开关版本 WHERE 开关键=?",
            (开关键,),
        ).fetchone()["m"]
        提议世代 = int(最大世代) + 1
        冲突编号 = 记冲突(
            conn, 开关键, 版本键, 现行键, 现行世代, 提议世代,
            "开关键已有唯一当前版本，单胜出拒绝并发入轨", 时刻, 载荷, 说明,
        )
        return {
            "版本键": 版本键, "开关键": 开关键, "结果": "冲突",
            "世代": 0, "当前键": 现行键, "冲突编号": 冲突编号,
        }

    # 空指针：取世代链下一号，落版本行、指针行——同票。
    世代 = int(conn.execute(
        "SELECT COALESCE(MAX(世代),0) AS m FROM 开关版本 WHERE 开关键=?",
        (开关键,),
    ).fetchone()["m"]) + 1
    conn.execute(
        "INSERT INTO 开关版本(版本键, 开关键, 版本号, 载荷, 状态, 入轨时, 说明, 世代) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (版本键, 开关键, 版本号, 载荷, "已入轨", 时刻, 说明, 世代),
    )
    conn.execute(
        """INSERT INTO 当前版本(开关键, 版本键, 世代, 更新时)
           VALUES (?,?,?,?)
           ON CONFLICT(开关键) DO UPDATE SET
             版本键=excluded.版本键, 世代=excluded.世代, 更新时=excluded.更新时""",
        (开关键, 版本键, 世代, 时刻),
    )
    return {
        "版本键": 版本键, "开关键": 开关键, "结果": "准入",
        "世代": 世代, "当前键": 版本键,
    }


def 核证(conn, 开关键: str | None = None) -> dict:
    """核证：行数 / 当前键 / 冲突单 / valid。

    valid 口径（甲）：活跃已入轨版本 ≤ 1；当前指针存在当且仅当有活跃版本；
    指针指向的版本必须真实存在；活跃版本必须就是当前指针所指之版。
    """
    if 开关键 is not None:
        return _核一键(conn, 开关键)

    键们 = set()
    for r in conn.execute("SELECT DISTINCT 开关键 FROM 开关版本"):
        键们.add(r["开关键"])
    for r in conn.execute("SELECT DISTINCT 开关键 FROM 当前版本"):
        键们.add(r["开关键"])
    for r in conn.execute("SELECT DISTINCT 开关键 FROM 冲突单"):
        键们.add(r["开关键"])
    项 = [_核一键(conn, k) for k in sorted(键们)]
    return {
        "架构": 架构,
        "口径": 口径,
        "项": 项,
        "有效": all(x["valid"] for x in 项) if 项 else True,
    }


def _核一键(conn, 开关键: str) -> dict:
    行 = conn.execute(
        "SELECT * FROM 开关版本 WHERE 开关键=? ORDER BY 世代", (开关键,)
    ).fetchall()
    行数 = len(行)
    活跃 = [r for r in 行 if r["状态"] in 状态_活跃]
    指针 = _现行(conn, 开关键)
    当前键 = 指针["版本键"] if 指针 else ""
    当前世代 = int(指针["世代"]) if 指针 else 0

    冲突 = [dict(r) for r in conn.execute(
        "SELECT * FROM 冲突单 WHERE 开关键=? ORDER BY 编号", (开关键,)
    )]

    valid = True
    if len(活跃) > 1:
        valid = False
    if 当前键:
        命中 = next((r for r in 行 if r["版本键"] == 当前键), None)
        if 命中 is None:
            valid = False                      # 指针悬空
        elif 命中["状态"] not in 状态_活跃:
            valid = False                      # 指针指向非活跃版
        if len(活跃) != 1 or 活跃[0]["版本键"] != 当前键:
            valid = False                      # 活跃版与指针不互证
    else:
        if 活跃:
            valid = False                      # 有活跃版却无指针
    return {
        "开关键": 开关键,
        "行数": 行数,
        "活跃数": len(活跃),
        "当前键": 当前键,
        "当前世代": 当前世代,
        "版本": [
            {"版本键": r["版本键"], "版本号": r["版本号"], "世代": int(r["世代"] or 0),
             "状态": r["状态"]}
            for r in 行
        ],
        "冲突单": 冲突,
        "冲突数": len(冲突),
        "valid": valid,
        "架构": 架构,
    }


def 列冲突(conn, 开关键: str = "") -> list:
    if 开关键:
        rows = conn.execute(
            "SELECT * FROM 冲突单 WHERE 开关键=? ORDER BY 编号", (开关键,)
        )
    else:
        rows = conn.execute("SELECT * FROM 冲突单 ORDER BY 编号 DESC")
    return [dict(r) for r in rows]
