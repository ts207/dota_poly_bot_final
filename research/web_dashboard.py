import asyncio
import json
import os
import sqlite3
import time
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.responses import HTMLResponse, JSONResponse
from starlette.websockets import WebSocket
from feeds.league_feed import fetch_and_store

DB_PATH = os.environ.get("DASH_DB_PATH", "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite")
ENV_PATH = "/home/irene/dota_poly_bot_final/data/last_discovered_target.env"
LEAGUE_POLL_INTERVAL = float(os.environ.get("LEAGUE_POLL_INTERVAL", "10"))

connected_ws: list[WebSocket] = []


def _load_env_mapping():
    mapping = {}
    if not os.path.exists(ENV_PATH):
        return mapping
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            mapping[k.strip()] = v.strip()
    return mapping


def _get_data():
    env = _load_env_mapping()
    if not os.path.exists(DB_PATH):
        return {"error": "no db"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1")
        row = cur.fetchone()
        dota = dict(row) if row else None

        cur.execute("SELECT * FROM market_ticks WHERE token_id LIKE 'COMBINED%' ORDER BY ts_ms DESC LIMIT 1")
        row = cur.fetchone()
        market = dict(row) if row else None

        cur.execute("SELECT token_id, best_bid, best_ask, mid, spread, bid_depth, ask_depth, ts_ms FROM market_ticks WHERE token_id NOT LIKE 'COMBINED%' ORDER BY ts_ms DESC LIMIT 10")
        seen = set()
        token_prices = {}
        for tr in cur.fetchall():
            tid = tr[0]
            if tid in seen:
                continue
            seen.add(tid)
            token_prices[tid] = {"bid": tr[1], "ask": tr[2], "mid": tr[3], "spread": tr[4], "bid_depth": tr[5], "ask_depth": tr[6], "ts_ms": tr[7]}

        cur.execute("SELECT * FROM live_league_games ORDER BY last_update_ts DESC")
        league_games = [dict(r) for r in cur.fetchall()]

        league_game = None
        players = []
        draft = []
        if dota:
            match_id = None
            r_clean = dota['radiant_team'].lower().replace('_', '').strip()
            d_clean = dota['dire_team'].lower().replace('_', '').strip()
            for lg in league_games:
                lg_r = lg['radiant_team_name'].lower().replace('_', '').strip()
                lg_d = lg['dire_team_name'].lower().replace('_', '').strip()
                if lg_r and (r_clean in lg_r or lg_r in r_clean) and (not lg_d or d_clean in lg_d or lg_d in d_clean):
                    match_id = lg['match_id']
                    league_game = lg
                    break
            if match_id:
                cur.execute("SELECT * FROM live_league_players WHERE match_id = ? ORDER BY team, net_worth DESC", (match_id,))
                players = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT * FROM live_draft WHERE match_id = ? ORDER BY team, slot", (match_id,))
                draft = [dict(r) for r in cur.fetchall()]
            else:
                draft = []

        cur.execute("SELECT * FROM signals ORDER BY ts_ms DESC LIMIT 10")
        signals = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM orders ORDER BY ts_ms DESC LIMIT 10")
        orders = [dict(r) for r in cur.fetchall()]

        radiant_tid = env.get("RADIANT_TOKEN_ID", "")
        dire_tid = env.get("DIRE_TOKEN_ID", "")

        return {
            "dota": dota,
            "market": market,
            "token_prices": token_prices,
            "league_game": league_game,
            "players": players,
            "draft": draft,
            "signals": signals,
            "orders": orders,
            "env": {
                "radiant_tid": radiant_tid,
                "dire_tid": dire_tid,
                "target_radiant": env.get("TARGET_RADIANT_TEAM", ""),
                "target_dire": env.get("TARGET_DIRE_TEAM", ""),
                "market_id": env.get("MARKET_ID", ""),
            }
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


async def homepage(request):
    return HTMLResponse(HTML)


async def api_state(request):
    return JSONResponse(_get_data())


async def ws_dash(ws: WebSocket):
    await ws.accept()
    connected_ws.append(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        if ws in connected_ws:
            connected_ws.remove(ws)


async def _league_poll():
    from dotenv import load_dotenv
    load_dotenv()
    while True:
        try:
            await fetch_and_store()
        except Exception:
            pass
        await asyncio.sleep(LEAGUE_POLL_INTERVAL)


async def _broadcast():
    while True:
        if connected_ws:
            data = _get_data()
            payload = json.dumps(data, default=str)
            dead = []
            for ws in connected_ws:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in connected_ws:
                    connected_ws.remove(ws)
        await asyncio.sleep(1)


async def lifespan(app):
    asyncio.ensure_future(_league_poll())
    asyncio.ensure_future(_broadcast())
    yield


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/api/state", api_state),
        WebSocketRoute("/ws", ws_dash),
    ],
    lifespan=lifespan,
)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dota Poly Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0e17;color:#c9d1d9;font-family:'JetBrains Mono','Fira Code',monospace;font-size:13px;overflow-x:hidden}
.grid{display:grid;grid-template-columns:240px 260px 1fr;grid-template-rows:auto auto auto auto;gap:10px;padding:10px;max-width:1600px;margin:0 auto}
.header{grid-column:1/-1;background:linear-gradient(135deg,#161b22,#0d1117);border:1px solid #21262d;border-radius:8px;padding:10px 18px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:16px;color:#58a6ff;font-weight:600}
.header .clock{color:#8b949e;font-size:14px}
.header .delay{color:#f0883e;font-size:12px}
.panel{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px;overflow:hidden}
.panel-title{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#8b949e;margin-bottom:8px;font-weight:600}
.row{display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid #0d1117}
.row:last-child{border:none}
.label{color:#8b949e}
.value{color:#c9d1d9;font-weight:500}
.value.green{color:#3fb950}
.value.red{color:#f85149}
.value.bold{color:#f0883e;font-weight:700}
.value.cyan{color:#58a6ff}
.players-panel{grid-column:3;grid-row:2/5}
table{width:100%;border-collapse:collapse}
th{text-align:left;color:#8b949e;font-size:10px;text-transform:uppercase;letter-spacing:0.8px;padding:4px 6px;border-bottom:1px solid #21262d;font-weight:600}
td{padding:4px 6px;border-bottom:1px solid #0d1117}
tr:hover{background:#1c2333}
.r{color:#3fb950}.d{color:#f85149}.gd{color:#ffd33d}.cyan{color:#58a6ff}
.signal-panel{grid-column:1/3}
.order-panel{grid-column:3}
.badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:600}
.badge.green{background:#1b4332;color:#3fb950}
.badge.red{background:#4c1d1d;color:#f85149}
.badge.yellow{background:#4a3b00;color:#ffd33d}
.badge.blue{background:#0d2948;color:#58a6ff}
.building-bar{display:flex;gap:2px;margin:2px 0}
.bldg-up{width:14px;height:10px;background:#3fb950;border-radius:2px}
.bldg-down{width:14px;height:10px;background:#f8514980;border-radius:2px}
</style>
</head>
<body>
<div class="grid">
<div class="header">
  <h1><span id="teams">Dota Poly Dashboard</span></h1>
  <div><span class="delay" id="delay"></span> <span class="clock" id="clock"></span></div>
</div>

<div class="panel" id="match-panel">
  <div class="panel-title">Match State</div>
  <div id="match-content"><span class="label">Connecting…</span></div>
</div>

<div class="panel" id="draft-panel">
  <div class="panel-title">Draft</div>
  <div id="draft-content"><span class="label">Connecting…</span></div>
</div>

<div class="panel" id="market-panel">
  <div class="panel-title">Polymarket</div>
  <div id="market-content"><span class="label">Connecting…</span></div>
</div>

<div class="panel players-panel" id="players-panel">
  <div class="panel-title">Live Players (Steam Web API)</div>
  <table>
    <thead><tr><th>Hero</th><th>T</th><th>Lvl</th><th>KDA</th><th style="text-align:right">NW</th><th style="text-align:right">LH/D</th><th style="text-align:right">GPM</th></tr></thead>
    <tbody id="players-body"></tbody>
  </table>
</div>

<div class="panel signal-panel" id="signals-panel">
  <div class="panel-title">Signals</div>
  <table><thead><tr><th>Time</th><th>Trigger</th><th>Edge</th><th>Action</th></tr></thead>
  <tbody id="signals-body"></tbody></table>
</div>

<div class="panel order-panel" id="orders-panel">
  <div class="panel-title">Orders</div>
  <table><thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Status</th></tr></thead>
  <tbody id="orders-body"></tbody></table>
</div>
</div>

<script>
const MAX_TOWERS=11, MAX_BARRACKS=6;
let lastData=null;

function fmt(n){return n==null?"—":n.toLocaleString()}
function ftime(s){if(s==null)return"—";const m=Math.floor(s/60),sec=Math.floor(s%60);return m+":"+String(sec).padStart(2,"0")}
function pct(v){return v==null?"—":(v*100).toFixed(1)+"%"}

function bitcount(v,bits){if(v==null||v===0)return 0;let c=0;for(let i=0;i<bits;i++)if(v&(1<<i))c++;return c}

function buildingBar(count,total){
  let h='<span class="building-bar">';
  for(let i=0;i<total;i++) h+=i<count?'<span class="bldg-up"></span>':'<span class="bldg-down"></span>';
  return h+'</span>';
}

function renderMatch(d){
  if(!d||!d.dota)return'<span class="label">No data</span>';
  const dt=d.dota, lg=d.league_game;
  let h='';
  h+=`<div class="row"><span class="label">Time</span><span class="value">${ftime(dt.game_time)}</span></div>`;
  h+=`<div class="row"><span class="label">Score</span><span class="value"><span class="r">${dt.radiant_score??0}</span> — <span class="d">${dt.dire_score??0}</span></span></div>`;
  h+=`<div class="row"><span class="label">Gold Lead</span><span class="value ${(dt.nw_diff||0)>=0?'green':'red'} bold">${fmt(dt.nw_diff)}</span></div>`;
  if(lg){
    const webLag=(dt.ts_ms/1000)-lg.last_update_ts;
    const lagCls=webLag<15?'green':webLag<45?'yellow':'red';
    h+=`<div class="row"><span class="label">Web API Lag</span><span class="value ${lagCls}">+${Math.round(webLag)}s</span></div>`;
    h+=`<div class="row" style="border:none;height:4px"></div>`;
    const rt=bitcount(lg.radiant_tower_state,11), dtow=bitcount(lg.dire_tower_state,11);
    const rrx=bitcount(lg.radiant_barracks_state,6), drx=bitcount(lg.dire_barracks_state,6);
    h+=`<div class="row"><span class="label">Rad Towers</span>${buildingBar(rt,MAX_TOWERS)}</div>`;
    h+=`<div class="row"><span class="label">Rad Rax</span>${buildingBar(rrx,MAX_BARRACKS)}</div>`;
    h+=`<div class="row"><span class="label">Dire Towers</span>${buildingBar(dtow,MAX_TOWERS)}</div>`;
    h+=`<div class="row"><span class="label">Dire Rax</span>${buildingBar(drx,MAX_BARRACKS)}</div>`;
    const rr=lg.radiant_roshan_timer, dr=lg.dire_roshan_timer;
    let roshTxt="—";
    if(rr!==null&&rr>0) roshTxt=`<span style="color:#f0883e">${Math.floor(rr/60)}:${String(rr%60).padStart(2,"0")}</span>`;
    else if(dr!==null&&dr>0) roshTxt=`<span style="color:#f85149">${Math.floor(dr/60)}:${String(dr%60).padStart(2,"0")}</span>`;
    else if(rr===0||dr===0) roshTxt='<span style="color:#3fb950;font-weight:700">Alive</span>';
    h+=`<div class="row"><span class="label">Roshan</span>${roshTxt}</div>`;
  } else {
    h+=`<div class="row"><span class="label">Web API</span><span class="value" style="color:#f85149">awaiting data</span></div>`;
  }
  return h;
}

function renderMarket(d){
  if(!d||!d.market)return'<span class="label">No data</span>';
  const m=d.market, env=d.env||{};
  let h='';
  h+=`<div class="row"><span class="label">Radiant Prob</span><span class="value cyan">${pct(m.mid)}</span></div>`;
  h+=`<div class="row"><span class="label">Spread</span><span class="value">${(m.spread||0).toFixed(4)}</span></div>`;
  h+=`<div class="row"><span class="label">Liquidity</span><span class="value">$${fmt(Math.round((m.bid_depth||0)+(m.ask_depth||0)))}</span></div>`;
  h+=`<div class="row" style="border:none;height:4px"></div>`;
  const tp=d.token_prices||{};
  const sorted=Object.entries(tp).sort((a,b)=>(b[1].mid||0)-(a[1].mid||0));
  for(const[tid,info]of sorted){
    let label=tid.slice(0,8)+'…';
    let cls='value';
    if(tid===env.radiant_tid){label=(env.target_radiant||'Rad');cls='value green';}
    else if(tid===env.dire_tid){label=(env.target_dire||'Dire');cls='value red';}
    h+=`<div class="row"><span class="${cls}">${label}</span><span class="value">B:${(info.bid||0).toFixed(2)} A:${(info.ask||0).toFixed(2)} M:${(info.mid||0).toFixed(3)}</span></div>`;
  }
  return h;
}

function renderPlayers(d){
  const players=d.players||[];
  if(!players.length)return'<tr><td colspan="7" style="color:#8b949e">awaiting data…</td></tr>';
  let h='';
  for(const p of players){
    const t=p.team===0?'<span class="r">R</span>':'<span class="d">D</span>';
    const hero=p.hero_name||p.name||'?';
    const deaths=p.deaths||p.death||0;
    h+=`<tr><td class="cyan">${hero.slice(0,16)}</td><td>${t}</td><td>${p.level??''}</td><td>${p.kills}/${deaths}/${p.assists}</td><td style="text-align:right" class="gd">${fmt(p.net_worth)}</td><td style="text-align:right">${p.last_hits??0}/${p.denies||0}</td><td style="text-align:right">${p.gpm??0}</td></tr>`;
  }
  return h;
}

function renderDraft(d){
  const draft=d.draft||[];
  if(!draft.length)return'<span class="label">No draft data</span>';
  const radPicks=draft.filter(x=>x.team===0&&x.is_pick===1).sort((a,b)=>a.slot-b.slot);
  const direPicks=draft.filter(x=>x.team===1&&x.is_pick===1).sort((a,b)=>a.slot-b.slot);
  const radBans=draft.filter(x=>x.team===0&&x.is_pick===0).sort((a,b)=>a.slot-b.slot);
  const direBans=draft.filter(x=>x.team===1&&x.is_pick===0).sort((a,b)=>a.slot-b.slot);
  let h='';
  if(radBans.length||direBans.length){
    h+='<div style="margin-bottom:6px"><span class="label" style="font-size:10px">BANS</span></div>';
    h+='<div style="display:flex;gap:12px;margin-bottom:8px">';
    h+='<div style="flex:1"><span class="r" style="font-size:10px">RAD</span><br/>';
    for(const b of radBans) h+=`<span style="color:#f8514980;font-size:11px">${b.hero_name||'? '+b.hero_id}</span> `;
    if(!radBans.length) h+='<span style="color:#555">—</span>';
    h+='</div><div style="flex:1"><span class="d" style="font-size:10px">DIRE</span><br/>';
    for(const b of direBans) h+=`<span style="color:#f8514980;font-size:11px">${b.hero_name||'? '+b.hero_id}</span> `;
    if(!direBans.length) h+='<span style="color:#555">—</span>';
    h+='</div></div>';
  }
  if(radPicks.length||direPicks.length){
    h+='<div style="margin-bottom:4px"><span class="label" style="font-size:10px">PICKS</span></div>';
    h+='<div style="display:flex;gap:12px">';
    h+='<div style="flex:1"><span class="r" style="font-size:10px">RAD</span><br/>';
    for(const p of radPicks) h+=`<span class="cyan" style="font-size:11px;font-weight:600">${p.hero_name||'? '+p.hero_id}</span> `;
    if(!radPicks.length) h+='<span style="color:#555">—</span>';
    h+='</div><div style="flex:1"><span class="d" style="font-size:10px">DIRE</span><br/>';
    for(const p of direPicks) h+=`<span class="cyan" style="font-size:11px;font-weight:600">${p.hero_name||'? '+p.hero_id}</span> `;
    if(!direPicks.length) h+='<span style="color:#555">—</span>';
    h+='</div></div>';
  }
  return h;
}

function renderSignals(d){
  const sigs=d.signals||[];
  if(!sigs.length)return'<tr><td colspan="4" style="color:#8b949e">none</td></tr>';
  let h='';
  for(const s of sigs.slice(0,8)){
    const t=new Date(s.ts_ms).toLocaleTimeString();
    const edge=(s.edge||0)*100;
    const ecls=edge>5?'green':edge>0?'yellow':'red';
    const act=s.action||'';
    const bcls=act.includes('BUY')?'green':'red';
    h+=`<tr><td>${t}</td><td>${s.trigger||''}</td><td class="${ecls}">${edge.toFixed(1)}%</td><td><span class="badge ${bcls}">${act}</span></td></tr>`;
  }
  return h;
}

function renderOrders(d){
  const ords=d.orders||[];
  if(!ords.length)return'<tr><td colspan="4" style="color:#8b949e">none</td></tr>';
  let h='';
  for(const o of ords.slice(0,8)){
    const t=new Date(o.ts_ms).toLocaleTimeString();
    const scls=o.status==='FILLED'?'green':'yellow';
    h+=`<tr><td>${t}</td><td>${o.side||''}</td><td>${(o.price||0).toFixed(3)}</td><td class="${scls}">${o.status||''}</td></tr>`;
  }
  return h;
}

function update(d){
  if(!d||d.error)return;
  lastData=d;
  const dt=d.dota;
  if(dt) document.getElementById('teams').textContent=`${dt.radiant_team||'?'} vs ${dt.dire_team||'?'}`;
  document.getElementById('clock').textContent=new Date().toLocaleTimeString();
  document.getElementById('match-content').innerHTML=renderMatch(d);
  document.getElementById('draft-content').innerHTML=renderDraft(d);
  document.getElementById('market-content').innerHTML=renderMarket(d);
  document.getElementById('players-body').innerHTML=renderPlayers(d);
  document.getElementById('signals-body').innerHTML=renderSignals(d);
  document.getElementById('orders-body').innerHTML=renderOrders(d);
}

let wsRetry=0;
function connect(){
  const proto=location.protocol==='https:'?'wss':'ws';
  const ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage=e=>{try{update(JSON.parse(e.data));wsRetry=0}catch(err){}};
  ws.onclose=()=>{
    wsRetry=Math.min(wsRetry+1,10);
    const delay=Math.min(1000*Math.pow(1.5,wsRetry),10000);
    document.getElementById('delay').textContent=`reconnecting (${Math.round(delay/1000)}s)`;
    setTimeout(connect,delay);
  };
  ws.onerror=()=>ws.close();
}
connect();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DASH_PORT", "8080"))
    print(f"Dashboard: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)