"""Phase 2 test runner web UI. Separate server on port 8001.

Run with: uv run python -m tests.phase2_runner.server
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure project root is importable when run as __main__
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text

from maya.db.models import User
from maya.db.session import get_sessionmaker
from maya.logging import configure_logging

from .runner import ScenarioResult, run_scenario
from .scenarios import SCENARIOS, Scenario, Variant

configure_logging("ERROR")

app = FastAPI(title="Maya Phase 2 Test Runner")

# In-memory results store: {scenario_id: {variant_id: ScenarioResult}}
_results: dict[str, dict[str, ScenarioResult]] = {}


# ── REST API ───────────────────────────────────────────────────────────────────

@app.get("/api/scenarios")
async def list_scenarios():
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "variants": [{"id": v.id, "name": v.name} for v in s.variants],
        }
        for s in SCENARIOS
    ]


@app.get("/api/results")
async def get_results():
    out = {}
    for sid, variants in _results.items():
        out[sid] = {}
        for vid, r in variants.items():
            d = asdict(r)
            out[sid][vid] = d
    return out


@app.post("/api/reset")
async def reset_data():
    sm = get_sessionmaker()
    deleted = 0
    async with sm() as session:
        rows = (await session.execute(
            select(User.id).where(User.description == "Phase 2 automated test")
        )).fetchall()
        uids = [str(r.id) for r in rows]
        if uids:
            await session.execute(
                text(
                    "DELETE FROM maya_memories "
                    "WHERE payload->>'user_id' = ANY(:uids)"
                ),
                {"uids": uids},
            )
            count = await session.execute(
                sa_delete(User).where(User.description == "Phase 2 automated test")
            )
            deleted = count.rowcount
        await session.commit()
    _results.clear()
    return {"deleted_users": deleted, "message": "Test data cleared."}


# ── WebSocket run endpoint ─────────────────────────────────────────────────────

@app.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    await websocket.accept()

    # Check API keys
    if not os.environ.get("OPENAI_API_KEY"):
        await websocket.send_json({
            "type": "error",
            "message": "OPENAI_API_KEY not set. Set it in .env and restart.",
        })
        await websocket.close()
        return

    try:
        data = await websocket.receive_json()
        cmd = data.get("cmd", "run_all")
        model_tier = data.get("model_tier", "cheap")
        auto_cleanup = data.get("auto_cleanup", True)
        target_sid = data.get("sid")
        target_vid = data.get("vid")

        scenarios_to_run: list[tuple[Scenario, Variant]] = []
        for scenario in SCENARIOS:
            if target_sid and scenario.id != target_sid:
                continue
            for variant in scenario.variants:
                if target_vid and variant.id != target_vid:
                    continue
                scenarios_to_run.append((scenario, variant))

        total = len(scenarios_to_run)
        await websocket.send_json({"type": "run_start", "total": total})

        passed = 0
        for idx, (scenario, variant) in enumerate(scenarios_to_run):
            await websocket.send_json({
                "type": "scenario_start",
                "sid": scenario.id,
                "vid": variant.id,
                "name": scenario.name,
                "variant_name": variant.name,
                "index": idx,
                "total": total,
            })

            async def send_event(event: dict) -> None:
                try:
                    await websocket.send_json(event)
                except Exception:
                    pass

            result = await run_scenario(
                scenario,
                variant,
                model_tier=model_tier,
                auto_cleanup=auto_cleanup,
                event_cb=send_event,
            )

            _results.setdefault(scenario.id, {})[variant.id] = result
            if result.status == "pass":
                passed += 1

            await websocket.send_json({
                "type": "scenario_done",
                "sid": scenario.id,
                "vid": variant.id,
                "status": result.status,
                "assertions": [asdict(a) for a in result.assertions],
                "memories": result.memories_snapshot,
                "duration_ms": result.duration_ms,
                "error": result.error,
            })

        await websocket.send_json({
            "type": "run_complete",
            "total": total,
            "passed": passed,
            "failed": total - passed,
        })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ── HTML UI ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maya Phase 2 Test Runner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#0d0d14;color:#d4d4e0;height:100vh;display:flex;flex-direction:column;overflow:hidden}
a{color:#7c6ef5}

/* ── Top bar ── */
header{background:#13131e;border-bottom:1px solid #2a2a40;padding:0 20px;height:52px;display:flex;align-items:center;gap:12px;flex-shrink:0}
.logo{font-weight:700;font-size:15px;color:#7c6ef5;margin-right:8px}
.logo span{color:#a78bfa}
header select,header label{font-size:13px;color:#c0c0d0}
header select{background:#1e1e2e;border:1px solid #3a3a55;color:#d4d4e0;padding:4px 8px;border-radius:6px;cursor:pointer}
.btn{padding:6px 14px;border-radius:7px;border:none;font-size:13px;font-weight:600;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-run{background:#5b21b6;color:#ede9fe}
.btn-all{background:#6d28d9;color:#ede9fe;padding:7px 16px}
.btn-reset{background:#7f1d1d;color:#fecaca}
.spacer{flex:1}
.dot{width:9px;height:9px;border-radius:50%;background:#374151;flex-shrink:0}
.dot.ok{background:#22c55e}
.dot.running{background:#f59e0b;animation:pulse .8s ease-in-out infinite}
.dot.error{background:#ef4444}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Layout ── */
.layout{display:flex;flex:1;overflow:hidden}
aside{width:270px;background:#111120;border-right:1px solid #2a2a40;overflow-y:auto;flex-shrink:0}
main{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}

/* ── Sidebar ── */
.sc-card{border-bottom:1px solid #1e1e30;cursor:pointer;transition:background .1s}
.sc-card:hover{background:#181828}
.sc-card.active{background:#1a1a2e}
.sc-head{padding:12px 14px 8px;display:flex;align-items:center;gap:8px}
.sc-name{font-size:13px;font-weight:600;flex:1}
.sc-run{padding:3px 9px;font-size:11px;background:#2d1b69;color:#c4b5fd;border:none;border-radius:5px;cursor:pointer}
.sc-run:hover{background:#3b1f8c}
.sc-vars{padding:0 14px 10px;display:flex;flex-wrap:wrap;gap:5px}
.chip{padding:3px 9px;border-radius:10px;font-size:11px;background:#1e1e30;color:#9090b0;cursor:pointer;border:none;transition:background .1s}
.chip:hover{background:#2a2a45}
.chip.pass{background:#14532d;color:#86efac}
.chip.fail{background:#7f1d1d;color:#fca5a5}
.chip.partial{background:#78350f;color:#fde68a}
.chip.error{background:#1f2937;color:#9ca3af}
.chip.running{background:#1e3a5f;color:#93c5fd;animation:pulse .8s infinite}
.chip.skipped{background:#2e1065;color:#c4b5fd}

/* ── Main panel ── */
.empty-state{text-align:center;margin:60px auto;color:#555;max-width:400px}
.empty-state h2{font-size:18px;margin-bottom:8px;color:#777}
.run-header{background:#13131e;border:1px solid #2a2a40;border-radius:10px;padding:14px 18px;display:flex;align-items:center;gap:10px}
.run-title{font-size:15px;font-weight:700}
.run-subtitle{font-size:12px;color:#888;margin-top:2px}
.status-badge{padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.status-badge.pass{background:#14532d;color:#86efac}
.status-badge.fail{background:#7f1d1d;color:#fca5a5}
.status-badge.partial{background:#78350f;color:#fde68a}
.status-badge.error{background:#1f2937;color:#9ca3af}
.status-badge.running{background:#1e3a5f;color:#93c5fd;animation:pulse .8s infinite}
.status-badge.skipped{background:#2e1065;color:#c4b5fd}

/* ── Sections ── */
section{background:#13131e;border:1px solid #2a2a40;border-radius:10px;overflow:hidden}
.sec-title{padding:10px 16px;font-size:12px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #1e1e30;background:#0f0f1a}
.sec-body{padding:14px 16px;display:flex;flex-direction:column;gap:8px}

/* ── Conversation ── */
.msg-wrap{display:flex;flex-direction:column;gap:2px;margin-bottom:4px}
.msg-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:.05em;padding:0 2px}
.msg{padding:9px 13px;border-radius:8px;font-size:13px;line-height:1.5;max-width:85%}
.msg.user{background:#1c2b4a;align-self:flex-end;color:#c0d8ff}
.msg.assistant{background:#1a1a2a;align-self:flex-start;color:#d0d0e0}
.msg.system{background:#1a1a1a;font-style:italic;color:#666;align-self:center;text-align:center;font-size:12px}
.typing{color:#555;font-style:italic;font-size:12px;padding:4px 8px}

/* ── Assertions ── */
.assert{display:flex;align-items:flex-start;gap:10px;padding:8px 12px;border-radius:7px;font-size:13px}
.assert.pass{background:#0d2b1a;border:1px solid #166534}
.assert.fail{background:#2b0d0d;border:1px solid #991b1b}
.assert.running{background:#0d1b2b;border:1px solid #1e3a5f}
.assert-icon{font-size:16px;flex-shrink:0;margin-top:1px}
.assert-body{flex:1}
.assert-label{font-weight:600;margin-bottom:3px}
.assert-detail{font-size:11px;color:#777;margin-top:2px}
.assert-resp{font-size:11px;color:#9090a0;margin-top:4px;padding:4px 8px;background:#0a0a14;border-radius:4px;border-left:2px solid #333;max-height:80px;overflow-y:auto}

/* ── Memory table ── */
table{width:100%;border-collapse:collapse}
th{font-size:11px;color:#666;font-weight:600;text-align:left;padding:6px 10px;border-bottom:1px solid #1e1e30;text-transform:uppercase;letter-spacing:.05em}
td{font-size:12px;padding:6px 10px;border-bottom:1px solid #1a1a28;vertical-align:top}
td.score{color:#888;width:55px;text-align:right}
td.ts{color:#555;width:120px;font-size:11px}
tr:last-child td{border-bottom:none}

/* ── Progress bar ── */
.progress-bar{height:3px;background:#2a2a40;border-radius:2px;overflow:hidden;margin-top:8px}
.progress-fill{height:100%;background:#7c6ef5;transition:width .3s ease}

/* ── Summary ── */
.summary{display:flex;gap:12px;padding:14px 16px}
.sum-item{flex:1;text-align:center;padding:10px;background:#0f0f1a;border-radius:8px}
.sum-num{font-size:24px;font-weight:700}
.sum-label{font-size:11px;color:#666;margin-top:2px}
.sum-num.pass{color:#22c55e}
.sum-num.fail{color:#ef4444}
.sum-num.total{color:#7c6ef5}

/* ── Config panel ── */
.config-inline{display:flex;align-items:center;gap:8px;font-size:12px;color:#888}
.config-inline select{background:#1e1e2e;border:1px solid #3a3a55;color:#d4d4e0;padding:3px 7px;border-radius:5px;font-size:12px}
.config-inline input[type=checkbox]{accent-color:#7c6ef5}
</style>
</head>
<body>

<header>
  <div class="logo">🧠 Maya <span>Phase 2</span> Tests</div>
  <div class="config-inline">
    Tier:
    <select id="tierSel">
      <option value="cheap">cheap (gpt-4o-mini)</option>
      <option value="main">main (Grok-3)</option>
    </select>
    <label><input type="checkbox" id="cleanupChk" checked> Auto-cleanup</label>
  </div>
  <div class="spacer"></div>
  <button class="btn btn-all" id="btnAll">▶ Run All</button>
  <button class="btn btn-reset" id="btnReset">⌫ Reset</button>
  <div class="dot" id="statusDot" title="Idle"></div>
</header>

<div class="layout">
  <aside id="sidebar"></aside>
  <main id="main">
    <div class="empty-state">
      <h2>Maya Phase 2 Test Runner</h2>
      <p>Select a scenario from the sidebar or click <strong>Run All</strong> to test all 6 scenarios.</p>
      <p style="margin-top:10px;font-size:12px;color:#444">RECENT_LIMIT=3 · requires OPENAI_API_KEY · port 8001</p>
    </div>
  </main>
</div>

<script>
const $ = id => document.getElementById(id);

// ─── State ───────────────────────────────────────────────────────────────────
let allScenarios = [];
let results = {};        // {sid: {vid: result}}
let activeKey = null;    // {sid, vid}
let ws = null;
let running = false;

// ─── Init ────────────────────────────────────────────────────────────────────
async function init() {
  allScenarios = await fetch('/api/scenarios').then(r => r.json());
  results = await fetch('/api/results').then(r => r.json());
  renderSidebar();
  if (Object.keys(results).length) {
    showSummaryPanel();
  }
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────
function renderSidebar() {
  const aside = $('sidebar');
  aside.innerHTML = allScenarios.map(s => {
    const vars = s.variants.map(v => {
      const status = results[s.id]?.[v.id]?.status ?? 'idle';
      const isActive = activeKey?.sid === s.id && activeKey?.vid === v.id;
      return `<button class="chip ${status}" onclick="viewVariant('${s.id}','${v.id}')" title="${v.name}">${v.id}</button>`;
    }).join('');
    const active = activeKey?.sid === s.id ? 'active' : '';
    return `
      <div class="sc-card ${active}" id="card-${s.id}">
        <div class="sc-head">
          <span class="sc-name">${s.name}</span>
          <button class="sc-run" onclick="runOne('${s.id}')">Run</button>
        </div>
        <div class="sc-vars" id="vars-${s.id}">${vars}</div>
      </div>`;
  }).join('');
}

function updateChip(sid, vid, status) {
  const container = $(`vars-${sid}`);
  if (!container) return;
  const chips = container.querySelectorAll('.chip');
  const variantOrder = allScenarios.find(s => s.id === sid)?.variants.map(v => v.id) ?? [];
  const idx = variantOrder.indexOf(vid);
  if (chips[idx]) {
    chips[idx].className = `chip ${status}`;
  }
}

// ─── View a variant result ────────────────────────────────────────────────────
function viewVariant(sid, vid) {
  activeKey = {sid, vid};
  renderSidebar();
  const r = results[sid]?.[vid];
  if (!r) {
    $('main').innerHTML = `<div class="empty-state"><h2>No result yet</h2><p>Run this scenario first.</p></div>`;
    return;
  }
  renderResultPanel(r);
}

function renderResultPanel(r) {
  const main = $('main');
  const statusIcon = {pass:'✅',fail:'❌',partial:'⚠️',error:'⚙️',skipped:'⏭'}[r.status] ?? '';
  const dur = r.duration_ms > 0 ? `${(r.duration_ms/1000).toFixed(1)}s` : '';

  const convHtml = r.conversation.map(m => {
    const cls = m.role === 'user' ? 'user' : 'assistant';
    const lbl = m.role === 'user' ? 'You' : 'Maya';
    return `<div class="msg-wrap"><div class="msg-label">${lbl}</div><div class="msg ${cls}">${escHtml(m.content)}</div></div>`;
  }).join('');

  const assertHtml = r.assertions.map(a => {
    const cls = a.passed ? 'pass' : 'fail';
    const icon = a.passed ? '✅' : '❌';
    const kws = a.require_keywords.join(', ');
    const forbid = a.forbid_keywords.length ? ` | forbid: ${a.forbid_keywords.join(', ')}` : '';
    return `
      <div class="assert ${cls}">
        <div class="assert-icon">${icon}</div>
        <div class="assert-body">
          <div class="assert-label">${escHtml(a.description)}</div>
          <div class="assert-detail">keywords: ${escHtml(kws)}${escHtml(forbid)}</div>
          <div class="assert-resp">${escHtml(a.actual_response)}</div>
        </div>
      </div>`;
  }).join('');

  const memHtml = r.memories_snapshot.length
    ? `<table><thead><tr><th>Memory</th><th>Stored</th></tr></thead><tbody>
        ${r.memories_snapshot.map(m =>
          `<tr><td>${escHtml(m.text)}</td><td class="ts">${(m.created_at||'').slice(0,16).replace('T',' ')}</td></tr>`
        ).join('')}
       </tbody></table>`
    : `<div style="color:#555;font-style:italic;font-size:13px">No memories captured.</div>`;

  const errHtml = r.error
    ? `<section><div class="sec-title">Error</div><div class="sec-body" style="color:#fca5a5;font-size:13px">${escHtml(r.error)}</div></section>`
    : '';

  main.innerHTML = `
    <div class="run-header">
      <div style="flex:1">
        <div class="run-title">${escHtml(r.scenario_name)}</div>
        <div class="run-subtitle">${escHtml(r.variant_name)} · ${dur}</div>
      </div>
      <div class="status-badge ${r.status}">${statusIcon} ${r.status.toUpperCase()}</div>
    </div>
    ${errHtml}
    <section>
      <div class="sec-title">Assertions (${r.assertions.filter(a=>a.passed).length}/${r.assertions.length} passed)</div>
      <div class="sec-body">${assertHtml || '<div style="color:#555;font-style:italic">No assertions.</div>'}</div>
    </section>
    <section>
      <div class="sec-title">Conversation (${r.conversation.length} messages)</div>
      <div class="sec-body" style="max-height:400px;overflow-y:auto">${convHtml}</div>
    </section>
    <section>
      <div class="sec-title">Memory Snapshot (${r.memories_snapshot.length} facts)</div>
      <div class="sec-body">${memHtml}</div>
    </section>
  `;
}

function showSummaryPanel() {
  let total = 0, passed = 0, failed = 0, partial = 0;
  for (const sid of Object.keys(results)) {
    for (const vid of Object.keys(results[sid])) {
      total++;
      const s = results[sid][vid].status;
      if (s === 'pass') passed++;
      else if (s === 'fail') failed++;
      else if (s === 'partial') partial++;
    }
  }
  $('main').innerHTML = `
    <div class="run-header">
      <div class="run-title">Last Run Summary</div>
    </div>
    <section>
      <div class="summary">
        <div class="sum-item"><div class="sum-num total">${total}</div><div class="sum-label">Total</div></div>
        <div class="sum-item"><div class="sum-num pass">${passed}</div><div class="sum-label">Passed</div></div>
        <div class="sum-item"><div class="sum-num fail">${failed}</div><div class="sum-label">Failed</div></div>
        <div class="sum-item"><div class="sum-num" style="color:#f59e0b">${partial}</div><div class="sum-label">Partial</div></div>
      </div>
    </section>
    <div style="color:#555;text-align:center;font-size:13px">Click any variant chip in the sidebar to view details.</div>
  `;
}

// ─── Live run panel ───────────────────────────────────────────────────────────
function startLivePanel(name, variantName, index, total) {
  activeKey = null;
  renderSidebar();
  const pct = total > 0 ? Math.round(index / total * 100) : 0;
  $('main').innerHTML = `
    <div class="run-header" id="liveHeader">
      <div style="flex:1">
        <div class="run-title" id="liveName">${escHtml(name)}</div>
        <div class="run-subtitle" id="liveVariant">${escHtml(variantName)}</div>
      </div>
      <div class="status-badge running" id="liveBadge">RUNNING</div>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progFill" style="width:${pct}%"></div></div>
    <section>
      <div class="sec-title">Live Conversation</div>
      <div class="sec-body" id="liveConv" style="max-height:350px;overflow-y:auto"></div>
    </section>
    <section>
      <div class="sec-title">Assertions</div>
      <div class="sec-body" id="liveAssert"></div>
    </section>
  `;
}

function appendConvMsg(role, content) {
  const container = $('liveConv');
  if (!container) return;
  const cls = role === 'user' ? 'user' : role === 'system' ? 'system' : 'assistant';
  const lbl = role === 'user' ? 'You' : role === 'system' ? '' : 'Maya';
  const html = `<div class="msg-wrap"><div class="msg-label">${lbl}</div><div class="msg ${cls}">${escHtml(content)}</div></div>`;
  container.insertAdjacentHTML('beforeend', html);
  container.scrollTop = container.scrollHeight;
}

function appendAssertion(a) {
  const container = $('liveAssert');
  if (!container) return;
  const cls = a.passed ? 'pass' : 'fail';
  const icon = a.passed ? '✅' : '❌';
  const kws = (a.require_keywords||[]).join(', ');
  const html = `
    <div class="assert ${cls}">
      <div class="assert-icon">${icon}</div>
      <div class="assert-body">
        <div class="assert-label">${escHtml(a.description)}</div>
        <div class="assert-detail">keywords: ${escHtml(kws)}</div>
        <div class="assert-resp">${escHtml(a.actual_response||'')}</div>
      </div>
    </div>`;
  container.insertAdjacentHTML('beforeend', html);
}

// ─── WebSocket runner ─────────────────────────────────────────────────────────
function startRun(cmd, sid, vid) {
  if (running) return;
  running = true;
  setDot('running');

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${protocol}://${location.host}/ws/run`);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      cmd,
      sid: sid || null,
      vid: vid || null,
      model_tier: $('tierSel').value,
      auto_cleanup: $('cleanupChk').checked,
    }));
  };

  ws.onmessage = evt => {
    const e = JSON.parse(evt.data);
    handleEvent(e);
  };

  ws.onerror = () => { setDot('error'); running = false; };
  ws.onclose = () => { running = false; if (document.querySelector('.dot.running')) setDot('idle'); };
}

function handleEvent(e) {
  switch (e.type) {
    case 'run_start':
      break;

    case 'scenario_start':
      updateChip(e.sid, e.vid, 'running');
      startLivePanel(e.name, e.variant_name, e.index, e.total);
      if ($('progFill')) $('progFill').style.width = `${Math.round(e.index / e.total * 100)}%`;
      break;

    case 'turn_sent':
      appendConvMsg('user', e.msg);
      $('liveConv') && ($('liveConv').insertAdjacentHTML('beforeend',
        '<div class="typing">Maya is thinking…</div>'));
      break;

    case 'turn_received':
      const typing = $('liveConv')?.querySelector('.typing');
      if (typing) typing.remove();
      appendConvMsg('assistant', e.response);
      break;

    case 'session_restart':
      appendConvMsg('system', `⟳ ${e.msg}`);
      break;

    case 'info':
      appendConvMsg('system', e.msg);
      break;

    case 'assertion':
      appendAssertion(e);
      break;

    case 'memories':
      // stored internally; shown after scenario_done
      break;

    case 'scenario_done': {
      updateChip(e.sid, e.vid, e.status);
      const b = $('liveBadge');
      if (b) { b.className = `status-badge ${e.status}`; b.textContent = e.status.toUpperCase(); }
      // Store result so clicking chip shows it
      if (!results[e.sid]) results[e.sid] = {};
      results[e.sid][e.vid] = {
        scenario_id: e.sid,
        variant_id: e.vid,
        scenario_name: '',
        variant_name: '',
        status: e.status,
        assertions: e.assertions,
        conversation: [],
        memories_snapshot: e.memories,
        duration_ms: e.duration_ms,
        error: e.error,
      };
      // Enrich with name from allScenarios
      const sc = allScenarios.find(s => s.id === e.sid);
      if (sc) {
        results[e.sid][e.vid].scenario_name = sc.name;
        results[e.sid][e.vid].variant_name = sc.variants.find(v => v.id === e.vid)?.name ?? e.vid;
      }
      break;
    }

    case 'run_complete':
      setDot('ok');
      running = false;
      renderSidebar();
      showSummaryPanel();
      if ($('progFill')) $('progFill').style.width = '100%';
      break;

    case 'error':
      appendConvMsg('system', `❌ Error: ${e.message}`);
      setDot('error');
      running = false;
      break;
  }
}

// ─── Buttons ──────────────────────────────────────────────────────────────────
$('btnAll').onclick = () => startRun('run_all');

function runOne(sid) {
  startRun('run_scenario', sid, null);
}

$('btnReset').onclick = async () => {
  if (!confirm('Delete all test users and Mem0 memories? This cannot be undone.')) return;
  const r = await fetch('/api/reset', {method:'POST'}).then(r => r.json());
  results = {};
  renderSidebar();
  $('main').innerHTML = `<div class="empty-state"><h2>Reset complete</h2><p>${r.message}</p></div>`;
  setDot('idle');
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function setDot(state) {
  const d = $('statusDot');
  d.className = 'dot' + (state !== 'idle' ? ` ${state}` : '');
  d.title = {ok:'Ready',running:'Running…',error:'Error',idle:'Idle'}[state] ?? state;
}

function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
