import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

export default function 下发票() {
  const [rows, setRows] = useState([]);
  const [版, set版] = useState([]);
  const [讯, set讯] = useState("");
  const [试版本, set试版本] = useState("");
  const 刷 = async () => {
    const [t, v] = await Promise.all([get("/下发票"), get("/开关版本")]);
    setRows(t); set版(v);
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);

  // 对非当前版下发：甲口径必须失败闭（409/400）。
  const 试下发 = async (版本键) => {
    set讯("");
    try {
      const r = await post("/下发", {
        版本键, 桶键: "checkout.new_tax-gray10", 票号: `票-试-${版本键}-${Date.now()}`,
      });
      set讯(`下发成功 · 钉版 ${r.钉版} · 世代 ${r.世代}`);
    } catch (e) {
      set讯(`已拒（失败闭）：${e.message}`);
    }
    await 刷();
  };

  return (
    <div>
      <h1 className="题">下发票</h1>
      <p className="述">
        下发必须<b>钉版</b>：版本键须等于该开关键当前指针。非当前版一律失败闭；票号幂等。
      </p>
      <div className="行">
        <button onClick={async () => { await postFixture("下发样例"); await 刷(); set讯("已灌下发样例"); }}>灌下发样例</button>
        <button className="次" onClick={() => 刷()}>刷新</button>
      </div>
      <div className="行">
        <input className="次" style={{ padding: "0.5rem 0.7rem", borderRadius: 2, border: "1px solid var(--线)", background: "rgba(255,255,255,0.7)", font: "inherit", minWidth: 240 }}
          placeholder="版本键（试对非当前版下发）" value={试版本} onChange={(e) => set试版本(e.target.value)} />
        <button className="次" disabled={!试版本} onClick={() => 试下发(试版本)}>试下发</button>
        {版.map((v) => (
          <button key={v.版本键} className="次" onClick={() => 试下发(v.版本键)}>{v.版本键}</button>
        ))}
      </div>
      {讯 && <p className="讯">{讯}</p>}
      {!rows.length ? <div className="空态">尚无下发票（需先入轨+分桶）</div> : (
        <table>
          <thead><tr><th>票号</th><th>版本键</th><th>桶键</th><th>钉版</th><th>世代</th><th>状态</th><th>下发时</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.票号}><td>{r.票号}</td><td>{r.版本键}</td><td>{r.桶键}</td>
            <td><code className="mono">{r.钉版 || "—"}</code></td><td>{r.世代}</td>
            <td><span className="徽章 通">{r.状态}</span></td><td>{r.下发时}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
