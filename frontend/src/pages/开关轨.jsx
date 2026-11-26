import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

export default function 开关轨() {
  const [rows, setRows] = useState([]);
  const [核, set核] = useState(null);
  const [冲突, set冲突] = useState([]);
  const [讯, set讯] = useState("");
  const [键, set键] = useState("");
  const [跑, set跑] = useState(false);

  const 刷 = async () => {
    const [v, k, c] = await Promise.all([
      get("/开关版本"),
      get(键 ? `/核证?开关键=${encodeURIComponent(键)}` : "/核证"),
      get(键 ? `/冲突单?开关键=${encodeURIComponent(键)}` : "/冲突单"),
    ]);
    setRows(v); set核(k); set冲突(c);
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);
  const 定键 = (k) => 核 || {};
  const 焦点 = 键 ? 定键(核) : {};

  // 并发 v3/v4：两客户端同时给同一开关键塞版本；库内仅一版已入轨、当前唯一。
  const 并发 = async () => {
    set跑(true);
    try {
      const d = await post("/竞态/开关键", { 开关键: 键 || "checkout.new_tax", 版本号: [3, 4] });
      const 断言 = d.断言 || {};
      let 讯 = `胜出 ${d.胜出.join(",") || "无"} · 冲突 ${d.冲突.length} 单 · ` +
        `库内 ${断言["库内版本数"]} 行 · 当前唯一 ${断言["当前唯一"] ? "✓" : "✗"} · valid ${断言.valid ? "✓" : "✗"}`;
      if (d.胜出.length !== 1 || !断言.valid || !断言["当前唯一"]) {
        讯 = "FAIL · " + 讯;
      }
      set讯(讯);
      set键(d.开关键);
      await 刷();
    } catch (e) { set讯(String(e)); }
    finally { set跑(false); }
  };

  const 当前键们 = new Set((核?.项 || []).map((x) => x.当前键).filter(Boolean));

  return (
    <div>
      <h1 className="题">开关轨</h1>
      <p className="述">
        开关键竞态准入 · <b>架构甲（单胜出）</b>。同开关键任一时刻仅一版已入轨，当前指针唯一；
        并发冲突方不入库、留冲突单可查；下发必须钉当前版本键。
      </p>
      <div className="行">
        <button onClick={async () => { await postFixture("入轨样例"); await 刷(); set讯("已灌入轨样例"); }}>灌入轨样例</button>
        <button className="信" disabled={跑} onClick={并发}>{跑 ? "并发中…" : "并发塞 v3/v4"}</button>
        <input className="次" style={{ padding: "0.5rem 0.7rem", borderRadius: 2, border: "1px solid var(--线)", background: "rgba(255,255,255,0.7)", font: "inherit" }}
          placeholder="开关键（留空则全核）" value={键} onChange={(e) => set键(e.target.value)} />
        <button className="次" onClick={() => 刷().catch((e) => set讯(String(e)))}>刷新</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}

      <div className="提示条">
        {键 ? (
          焦点 && 焦点.开关键 ? (
            <>核证 <code>{焦点.开关键}</code>：行数 <b>{焦点.行数}</b> · 活跃 <b>{焦点.活跃数}</b> ·
              当前 <code className="mono">{焦点.当前键 || "空"}</code> · 世代 <b>{焦点.当前世代}</b> ·
              冲突单 <b>{焦点.冲突数}</b> ·{" "}
              <span className={"徽章 " + (焦点.valid ? "通" : "败")}>{焦点.valid ? "valid" : "invalid"}</span></>
          ) : <>该开关键无记录</>
        ) : (
          核 && (<>全核：{核.项.length} 键 ·{" "}<span className={"徽章 " + (核.有效 ? "通" : "败")}>
            {核.有效 ? "有效" : "存在无效键"}</span></>)
        )}
      </div>

      {!rows.length ? <div className="空态">尚无版本，先灌入轨样例或并发塞 v3/v4</div> : (
        <table>
          <thead><tr><th>版本键</th><th>开关键</th><th>版本号</th><th>世代</th><th>状态</th><th>当前</th><th>入轨时</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.版本键}><td>{r.版本键}</td><td>{r.开关键}</td><td>{r.版本号}</td>
            <td>{r.世代}</td>
            <td><span className="徽章 通">{r.状态}</span></td>
            <td>{当前键们.has(r.版本键) ? <span className="徽章 信">当前</span> : "—"}</td>
            <td>{r.入轨时}</td></tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="题" style={{ fontSize: "1.05rem", marginTop: "1.6rem" }}>冲突单</h2>
      <p className="述">并发失败方留痕：被拒版本键 ↔ 现行版本键 ↔ 提议世代。禁止无审计覆盖。</p>
      {!冲突.length ? <div className="空态">无冲突（尚无并发败者）</div> : (
        <table>
          <thead><tr><th>#</th><th>开关键</th><th>被拒版本</th><th>现行版本</th><th>现行世代</th><th>提议世代</th><th>时刻</th><th>原因</th></tr></thead>
          <tbody>{冲突.map((r) => (
            <tr key={r.编号}><td>{r.编号}</td><td>{r.开关键}</td><td>{r.被拒版本键}</td>
            <td>{r.现行版本键}</td><td>{r.现行世代}</td><td>{r.提议世代}</td>
            <td>{r.时刻}</td><td>{r.原因}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
