import json
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接, 写事务
from app.modules.开关键竞态准入 import 核证, 列冲突, 准入, 架构, 口径
from app.services import 入轨, 分桶, 下发, 回读, 命运, 贯验, 目录

路由 = APIRouter(prefix="/api")


class 入轨请求(BaseModel):
    批次编号: str = ""
    版本: list = Field(default_factory=list)


class 分桶请求(BaseModel):
    桶键: str
    开关键: str
    桶类型: str = "百分比"
    规则: dict = Field(default_factory=dict)
    状态: str = "生效"


class 下发请求(BaseModel):
    票号: str = ""
    版本键: str
    桶键: str
    说明: str = ""


class 回读请求(BaseModel):
    证号: str = ""
    票号: str
    边缘键: str
    所见版本键: str = ""
    结果: str = "确认"
    说明: str = ""


class 回滚请求(BaseModel):
    票号: str
    说明: str = ""


class 失效请求(BaseModel):
    版本键: str
    说明: str = ""


class 竞态请求(BaseModel):
    开关键: str = "checkout.new_tax"
    版本号: list = Field(default_factory=lambda: [3, 4])


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "灰度轨",
        "领域": "基础设施",
        "子方向": "中间件",
        "骨架": "开关版本入轨→分桶灰度下发→回读确认→失效/回滚互证",
        "准入架构": 架构,
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/开关版本")
def 列版本(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 开关版本 WHERE 状态=? ORDER BY 入轨时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 开关版本 ORDER BY 入轨时 DESC")
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["载荷"] = json.loads(d["载荷"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/核证")
def 取核证(开关键: str = ""):
    """核证接口：给开关键则核一键；否则核全部并回总判。

    返回 行数 / 当前键 / 冲突单 / valid / 架构。
    """
    conn = 连接()
    try:
        return 核证(conn, 开关键 or None)
    finally:
        conn.close()


@路由.get("/冲突单")
def 取冲突(开关键: str = ""):
    conn = 连接()
    try:
        return 列冲突(conn, 开关键)
    finally:
        conn.close()


@路由.get("/分桶规")
def 列分桶():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 分桶规 ORDER BY 更新时 DESC"):
            d = dict(r)
            try:
                d["规则"] = json.loads(d["规则"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/下发票")
def 列下发(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 下发票 WHERE 状态=? ORDER BY 下发时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 下发票 ORDER BY 下发时 DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/回读证")
def 列回读():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 回读证 ORDER BY 回读时 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/命运账")
def 列命运():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 命运账 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/空桩")
def 列空桩():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 空桩 ORDER BY 名")]
    finally:
        conn.close()


@路由.post("/入轨")
def 做入轨(体: 入轨请求):
    return 入轨.入一批(体.model_dump())


@路由.post("/分桶")
def 做分桶(体: 分桶请求):
    return 分桶.写桶(体.model_dump())


@路由.post("/下发")
def 做下发(体: 下发请求):
    return 下发.下一票(体.model_dump())


@路由.post("/回读")
def 做回读(体: 回读请求):
    return 回读.记回读(体.model_dump())


@路由.post("/回滚")
def 做回滚(体: 回滚请求):
    return 命运.回滚票(体.model_dump())


@路由.post("/失效")
def 做失效(体: 失效请求):
    return 命运.失效版本(体.model_dump())


@路由.post("/竞态/开关键")
def 竞态准入(体: 竞态请求):
    """并发压测入口：两客户端同时给同一开关键塞 v3/v4。

    两线程各占独立连接、各自 BEGIN IMMEDIATE；后到者排队，重读指针，
    必看清已入轨的胜出版，从而只留冲突单、不入库。
    """
    开关键 = 体.开关键
    号们 = list(体.版本号) or [3, 4]
    结果: dict = {}
    栅栏 = threading.Barrier(len(号们))

    def 客户端(号):
        栅栏.wait()
        try:
            with 写事务() as conn:
                结果[号] = 准入(conn, {
                    "开关键": 开关键, "版本号": 号,
                    "版本键": f"{开关键}@{号}", "说明": "并发压测",
                })
        except Exception as e:  # 写锁排队超时等，失败闭
            结果[号] = {"开关键": 开关键, "版本号": 号, "结果": "失败",
                        "错误": f"{type(e).__name__}: {e}"}

    线程们 = [threading.Thread(target=客户端, args=(号,)) for 号 in 号们]
    for t in 线程们:
        t.start()
    for t in 线程们:
        t.join()

    项 = dict(sorted(结果.items()))
    胜出 = [v["版本键"] for v in 项.values() if v.get("结果") == "准入"]
    冲突 = [v for v in 项.values() if v.get("结果") == "冲突"]

    conn = 连接()
    try:
        核 = 核证(conn, 开关键)
    finally:
        conn.close()

    断言 = {
        "当前唯一": 核["活跃数"] <= 1,
        "指针非双": bool(核["当前键"]) and 核["活跃数"] == 1,
        "冲突方留痕": all(v.get("冲突编号") for v in 冲突) if 冲突 else True,
        "库内版本数": 核["行数"],
        "valid": 核["valid"],
    }
    return {
        "开关键": 开关键,
        "架构": 架构,
        "口径": 口径,
        "结果": 项,
        "胜出": 胜出,
        "冲突": 冲突,
        "核证": 核,
        "断言": 断言,
    }


@路由.post("/装载/夹具")
def 装夹具(名: str = "入轨样例"):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    体 = json.loads(路径.read_text(encoding="utf-8"))
    类型 = 体.get("类型", "入轨")
    if 类型 == "入轨":
        return 入轨.入一批(体)
    if 类型 == "分桶":
        outs = [分桶.写桶(x) for x in 体.get("分桶") or []]
        return {"类型": "分桶", "结果": outs}
    if 类型 == "下发":
        return 下发.装下发夹具(体)
    if 类型 == "回读":
        return 回读.装回读夹具(体)
    if 类型 == "回滚":
        return 命运.回滚票(体)
    raise HTTPException(400, f"未知夹具类型:{类型}")


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 轨贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()
