from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import json
import os
from pathlib import Path

app = FastAPI()

CMD_FILE = Path("data/manual_commands.json")
LOG_FILE = Path("data/bot_g2.log")

@app.get("/", response_class=HTMLResponse)
async def index():
    return r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ANTIGRAVITY | Dota 2 Trading Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Roboto+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0a0b10;
            --panel-bg: #141620;
            --accent-blue: #00f2ff;
            --accent-green: #00ff88;
            --accent-red: #ff3366;
            --text-main: #e0e6ed;
            --text-dim: #8492a6;
        }

        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            font-family: 'Roboto Mono', monospace;
            margin: 0;
            padding: 20px;
            overflow-x: hidden;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--accent-blue);
            padding-bottom: 10px;
            margin-bottom: 20px;
        }

        .title {
            font-family: 'Orbitron', sans-serif;
            font-size: 24px;
            letter-spacing: 2px;
            color: var(--accent-blue);
            text-shadow: 0 0 10px rgba(0, 242, 255, 0.5);
        }

        .status-badge {
            padding: 5px 15px;
            border-radius: 20px;
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid var(--accent-green);
            color: var(--accent-green);
            font-size: 12px;
        }

        .grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }

        .panel {
            background: var(--panel-bg);
            border: 1px solid #2d3142;
            padding: 20px;
            border-radius: 8px;
            position: relative;
        }

        .panel-title {
            font-size: 14px;
            color: var(--text-dim);
            margin-bottom: 15px;
            text-transform: uppercase;
        }

        .action-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }

        .btn {
            padding: 20px;
            border: none;
            border-radius: 4px;
            font-family: 'Orbitron', sans-serif;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
            text-transform: uppercase;
        }

        .btn-buy-r { background: var(--accent-green); color: black; box-shadow: 0 0 15px rgba(0, 255, 136, 0.3); }
        .btn-buy-d { background: var(--accent-red); color: white; box-shadow: 0 0 15px rgba(255, 51, 102, 0.3); }
        .btn-exit { 
            grid-column: span 2; 
            background: #2d3142; 
            color: white; 
            margin-top: 10px;
        }

        .btn:hover { transform: translateY(-2px); filter: brightness(1.1); }
        .btn:active { transform: translateY(0); }

        .log-area {
            height: 300px;
            overflow-y: auto;
            background: #000;
            padding: 10px;
            font-size: 12px;
            border: 1px solid #2d3142;
        }

        .log-line { margin-bottom: 4px; border-bottom: 1px solid #111; padding-bottom: 2px; }
        .log-time { color: var(--accent-blue); margin-right: 10px; }

        .stat-value { font-size: 32px; font-weight: bold; color: white; margin-bottom: 5px; }
        .stat-label { font-size: 12px; color: var(--text-dim); }

        .flash { animation: flash-anim 0.5s; }
        @keyframes flash-anim {
            0% { background: rgba(0, 242, 255, 0.2); }
            100% { background: transparent; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">ANTIGRAVITY // DOTA.TERMINAL</div>
        <div class="status-badge" id="status">FEED: LIVE</div>
    </div>

    <div class="grid">
        <div class="panel">
            <div class="panel-title">Real-Time Strategy Feed</div>
            <div class="log-area" id="logs">
                <div class="log-line">Connecting to bot streams...</div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-title">Manual Execution</div>
            <div class="action-grid">
                <button class="btn btn-buy-r" onclick="sendCommand('FORCE_BUY_RADIANT')">BUY RADIANT</button>
                <button class="btn btn-buy-d" onclick="sendCommand('FORCE_BUY_DIRE')">BUY DIRE</button>
                <button class="btn btn-exit" onclick="sendCommand('FORCE_EXIT')">EMERGENCY EXIT</button>
            </div>
            
            <div style="margin-top: 30px;">
                <div class="panel-title">Market Context</div>
                <div id="stats">
                    <div style="margin-bottom: 15px;">
                        <div class="stat-value" id="val-time">--m</div>
                        <div class="stat-label">GAME TIME</div>
                    </div>
                    <div>
                        <div class="stat-value" id="val-mid">--.---</div>
                        <div class="stat-label">RADIANT MID PRICE</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function sendCommand(action) {
            const btn = event.target;
            btn.style.opacity = "0.5";
            try {
                const res = await fetch(`/command?action=${action}`);
                const data = await res.json();
                console.log("Command response:", data);
            } catch (e) {
                console.error("Command failed:", e);
            }
            setTimeout(() => btn.style.opacity = "1", 500);
        }

        async function update() {
            try {
                const res = await fetch('/status');
                const data = await res.json();
                
                // Update Logs
                const logEl = document.getElementById('logs');
                logEl.innerHTML = data.logs.map(line => {
                    return `<div class="log-line">${line}</div>`;
                }).join('');
                logEl.scrollTop = logEl.scrollHeight;

                // Update Stats
                const lastLine = data.logs[data.logs.length - 1] || "";
                const timeMatch = lastLine.match(/Time=(\d+)m/);
                const midMatch = lastLine.match(/CombinedMid=([\d\.]+)/);
                
                if (timeMatch) document.getElementById('val-time').innerText = timeMatch[1] + "m";
                if (midMatch) document.getElementById('val-mid').innerText = midMatch[1];

            } catch (e) {}
        }

        setInterval(update, 1000);
    </script>
</body>
</html>
    """

@app.get("/status")
async def get_status():
    logs = []
    if LOG_FILE.exists():
        with open(LOG_FILE, "r") as f:
            logs = f.readlines()[-20:] # Last 20 lines
    return {"logs": [l.strip() for l in logs]}

@app.get("/command")
async def send_command(action: str):
    CMD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CMD_FILE, "w") as f:
        json.dump({"action": action, "ts": int(os.times()[4])}, f)
    return {"status": "ok", "action": action}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
