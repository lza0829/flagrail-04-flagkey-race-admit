import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "灰度轨.db"

# 写锁等待上限：并发准入时后到者排队，超时即失败闭，不做无审计覆盖。
库超时秒 = float(os.environ.get("库超时秒", "15"))


def 连接() -> sqlite3.Connection:
    """只读/自动提交连接。用于查询与小写入。"""
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=库超时秒)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = %d" % int(库超时秒 * 1000))
    return c


def 写连接() -> sqlite3.Connection:
    """显式事务连接（autocommit）：由调用方显式 BEGIN IMMEDIATE / COMMIT / ROLLBACK。"""
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=库超时秒, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = %d" % int(库超时秒 * 1000))
    return c


@contextmanager
def 写事务():
    """BEGIN IMMEDIATE 独占写事务：入轨、下发、命运的同票原子单元。

    同一时刻仅一个写事务，后到者排队（busy_timeout），超时抛 OperationalError。
    异常即回滚，绝不留下半截指针/世代。
    """
    c = 写连接()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except BaseException:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()
