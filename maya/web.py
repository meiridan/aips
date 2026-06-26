"""Simple web UI for Maya with debug flow visualization."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from maya.config import get_settings
from maya.telegram.service import get_telegram_service
from maya.conversation.orchestrator import (
    MEMORY_LIMIT,
    RECENT_LIMIT,
    Orchestrator,
)
from maya.companions.singleton import resolve_singleton
from maya.db.models import Message
from maya.db.session import get_sessionmaker
from maya.logging import configure_logging

# Re-exported so callers/tests can confirm the web path uses the shared
# orchestrator constants instead of hardcoded context limits (regression guard
# for the old 3/10 duplication bug — now structurally impossible after the
# single-orchestrator refactor).
__all__ = ["app", "MEMORY_LIMIT", "RECENT_LIMIT"]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Register the Telegram webhook on boot when fully configured (no-op locally)."""
    settings = get_settings()
    service = get_telegram_service()
    if service is not None and settings.public_base_url:
        url = f"{settings.public_base_url.rstrip('/')}/telegram/webhook"
        await service.client.set_webhook(url, settings.telegram_webhook_secret)
    yield


app = FastAPI(title="Maya Web UI", lifespan=lifespan)


# Configure logging
configure_logging(get_settings().litellm_log)


@app.get("/")
async def get_index():
    """Serve the main HTML page."""
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Maya - Chat & Debug</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            height: 100vh;
            display: flex;
            background: #f5f5f5;
        }
        
        /* Left Panel - Chat */
        .chat-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: white;
            border-right: 2px solid #e0e0e0;
        }
        
        .chat-header {
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .chat-header h1 {
            font-size: 24px;
            margin-bottom: 5px;
        }
        
        .chat-header p {
            opacity: 0.9;
            font-size: 14px;
        }
        
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .message {
            padding: 12px 16px;
            border-radius: 12px;
            max-width: 80%;
            word-wrap: break-word;
        }
        
        .message.user {
            background: #667eea;
            color: white;
            align-self: flex-end;
            margin-left: auto;
        }
        
        .message.assistant {
            background: #f0f0f0;
            color: #333;
            align-self: flex-start;
        }
        
        .message .role {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 4px;
            opacity: 0.8;
        }
        
        .input-area {
            padding: 20px;
            border-top: 1px solid #e0e0e0;
            background: white;
        }
        
        .input-container {
            display: flex;
            gap: 10px;
        }
        
        input {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
        }
        
        input:focus {
            border-color: #667eea;
        }
        
        button {
            padding: 12px 24px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: #5568d3;
        }
        
        button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        /* Right Panel - Debug */
        .debug-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: #1e1e1e;
        }
        
        .debug-header {
            padding: 20px;
            background: #2d2d2d;
            color: #fff;
            border-bottom: 1px solid #3d3d3d;
        }
        
        .debug-header h2 {
            font-size: 18px;
            margin-bottom: 5px;
        }
        
        .debug-header p {
            opacity: 0.7;
            font-size: 12px;
        }
        
        .debug-content {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 12px;
            color: #d4d4d4;
        }
        
        .debug-entry {
            margin-bottom: 16px;
            padding: 12px;
            background: #2d2d2d;
            border-radius: 6px;
            border-left: 3px solid #667eea;
        }
        
        .debug-entry.step {
            border-left-color: #4ade80;
        }
        
        .debug-entry.llm {
            border-left-color: #fbbf24;
        }
        
        .debug-entry.memory {
            border-left-color: #ec4899;
        }
        
        .debug-entry.error {
            border-left-color: #ef4444;
        }
        
        .debug-entry .timestamp {
            color: #888;
            font-size: 10px;
            margin-bottom: 4px;
        }
        
        .debug-entry .label {
            color: #667eea;
            font-weight: 600;
            margin-bottom: 6px;
        }
        
        .debug-entry.step .label { color: #4ade80; }
        .debug-entry.llm .label { color: #fbbf24; }
        .debug-entry.memory .label { color: #ec4899; }
        .debug-entry.error .label { color: #ef4444; }
        
        .debug-entry pre {
            color: #d4d4d4;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .connection-status {
            padding: 8px 12px;
            background: #2d2d2d;
            border-top: 1px solid #3d3d3d;
            color: #888;
            font-size: 11px;
            text-align: center;
        }
        
        .connection-status.connected {
            color: #4ade80;
        }
        
        .connection-status.disconnected {
            color: #ef4444;
        }

        /* Mobile tab bar — hidden on desktop */
        .tab-bar {
            display: none;
        }

        @media (max-width: 768px) {
            body {
                flex-direction: column;
                height: 100dvh;
            }

            .tab-bar {
                display: flex;
                background: #2d2d2d;
                flex-shrink: 0;
            }

            .tab-bar .tab {
                flex: 1;
                border-radius: 0;
                background: #2d2d2d;
                color: #aaa;
                padding: 14px;
                font-size: 15px;
                font-weight: 600;
                position: relative;
            }

            .tab-bar .tab.active {
                background: #667eea;
                color: #fff;
            }

            .tab-bar .tab.has-new::after {
                content: '';
                position: absolute;
                top: 10px;
                right: 20px;
                width: 8px;
                height: 8px;
                background: #4ade80;
                border-radius: 50%;
            }

            /* Only the active panel is shown on mobile */
            .chat-panel,
            .debug-panel {
                display: none;
                width: 100%;
                flex: 1;
                min-height: 0;
                border-right: none;
            }

            body.show-chat .chat-panel { display: flex; }
            body.show-debug .debug-panel { display: flex; }

            .chat-header h1 { font-size: 20px; }
            .chat-header,
            .debug-header { padding: 14px 16px; }
            .messages,
            .debug-content { padding: 14px; }
            .input-area { padding: 14px; padding-bottom: max(14px, env(safe-area-inset-bottom)); }

            .message { max-width: 88%; }

            /* 16px input prevents iOS auto-zoom on focus */
            input { font-size: 16px; }
        }
    </style>
</head>
<body class="show-chat">
    <div class="tab-bar">
        <button id="tab-chat" class="tab active" onclick="switchTab('chat')">💬 Chat</button>
        <button id="tab-debug" class="tab" onclick="switchTab('debug')">🔍 Debug</button>
    </div>
    <div class="chat-panel">
        <div class="chat-header">
            <h1>💬 Maya Chat</h1>
            <p>Your AI Companion</p>
        </div>
        <div class="messages" id="messages">
        </div>
        <div class="input-area">
            <div class="input-container">
                <input type="text" id="messageInput" placeholder="Type your message..." dir="auto" />
                <button id="sendButton" onclick="sendMessage()">Send</button>
            </div>
        </div>
    </div>
    
    <div class="debug-panel">
        <div class="debug-header">
            <h2>🔍 Debug Flow</h2>
            <p>Watch what happens behind the scenes</p>
        </div>
        <div class="debug-content" id="debugContent"></div>
        <div class="connection-status" id="connectionStatus">Connecting...</div>
    </div>

    <script>
        let ws = null;
        let isConnected = false;
        let historyLoading = true;
        let streamEl = null;  // content div of the in-flight assistant bubble

        function connect() {
            const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${wsProto}//${window.location.host}/ws`);
            historyLoading = true;
            document.getElementById('messages').innerHTML = '';

            ws.onopen = () => {
                isConnected = true;
                updateConnectionStatus();
                addDebugEntry('system', 'Connected to Maya server', {});
            };

            ws.onclose = () => {
                isConnected = false;
                updateConnectionStatus();
                addDebugEntry('error', 'Disconnected from server', {});
                setTimeout(connect, 2000);
            };

            ws.onerror = (error) => {
                addDebugEntry('error', 'WebSocket error', { error: error.toString() });
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'history_end') {
                    historyLoading = false;
                    const messagesDiv = document.getElementById('messages');
                    if (messagesDiv.children.length === 0) {
                        addMessage('assistant', "Hi! I'm Maya. What's on your mind?");
                    } else {
                        // If last message is from user (no assistant response yet),
                        // the response is still being generated — reload in 3s to pick it up.
                        const msgs = messagesDiv.querySelectorAll('.message');
                        const last = msgs[msgs.length - 1];
                        if (last && last.classList.contains('user')) {
                            addMessage('assistant', '…');
                            setTimeout(() => location.reload(), 3000);
                        }
                    }
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                } else if (data.type === 'message') {
                    addMessage(data.role, data.content);
                } else if (data.type === 'message_start') {
                    streamEl = beginAssistantMessage();
                } else if (data.type === 'message_chunk') {
                    if (!streamEl) streamEl = beginAssistantMessage();
                    streamEl.textContent += data.content;
                    const m = document.getElementById('messages');
                    m.scrollTop = m.scrollHeight;
                } else if (data.type === 'message_end') {
                    streamEl = null;
                    const input = document.getElementById('messageInput');
                    const sendButton = document.getElementById('sendButton');
                    input.disabled = false; sendButton.disabled = false; input.focus();
                } else if (data.type === 'debug') {
                    addDebugEntry(data.category, data.label, data.data);
                }
            };
        }

        function updateConnectionStatus() {
            const status = document.getElementById('connectionStatus');
            if (isConnected) {
                status.textContent = '● Connected';
                status.className = 'connection-status connected';
            } else {
                status.textContent = '● Disconnected';
                status.className = 'connection-status disconnected';
            }
        }

        function addMessage(role, content) {
            const messagesDiv = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}`;

            const roleDiv = document.createElement('div');
            roleDiv.className = 'role';
            roleDiv.textContent = role === 'user' ? 'You' : 'Maya';

            const contentDiv = document.createElement('div');
            contentDiv.dir = 'auto';
            contentDiv.textContent = content;

            messageDiv.appendChild(roleDiv);
            messageDiv.appendChild(contentDiv);
            messagesDiv.appendChild(messageDiv);
            if (!historyLoading) {
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }
        }

        // Create an empty assistant bubble and return its content div so stream
        // chunks can be appended into it as they arrive.
        function beginAssistantMessage() {
            const messagesDiv = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message assistant';
            const roleDiv = document.createElement('div');
            roleDiv.className = 'role';
            roleDiv.textContent = 'Maya';
            const contentDiv = document.createElement('div');
            contentDiv.dir = 'auto';
            contentDiv.textContent = '';
            messageDiv.appendChild(roleDiv);
            messageDiv.appendChild(contentDiv);
            messagesDiv.appendChild(messageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            return contentDiv;
        }

        function addDebugEntry(category, label, data) {
            const debugDiv = document.getElementById('debugContent');
            const entryDiv = document.createElement('div');
            entryDiv.className = `debug-entry ${category}`;
            
            const timestamp = new Date().toLocaleTimeString();
            const timestampDiv = document.createElement('div');
            timestampDiv.className = 'timestamp';
            timestampDiv.textContent = timestamp;
            
            const labelDiv = document.createElement('div');
            labelDiv.className = 'label';
            labelDiv.textContent = label;
            
            const dataDiv = document.createElement('pre');
            dataDiv.textContent = JSON.stringify(data, null, 2);
            
            entryDiv.appendChild(timestampDiv);
            entryDiv.appendChild(labelDiv);
            if (Object.keys(data).length > 0) {
                entryDiv.appendChild(dataDiv);
            }
            
            debugDiv.appendChild(entryDiv);
            debugDiv.scrollTop = debugDiv.scrollHeight;

            // On mobile, badge the Debug tab when it's not the active view
            if (window.matchMedia('(max-width: 768px)').matches &&
                !document.body.classList.contains('show-debug')) {
                document.getElementById('tab-debug').classList.add('has-new');
            }
        }
        
        function sendMessage() {
            const input = document.getElementById('messageInput');
            const sendButton = document.getElementById('sendButton');
            const message = input.value.trim();
            
            if (!message || !isConnected) return;
            
            // Disable input while processing
            input.disabled = true;
            sendButton.disabled = true;
            
            // Send message
            ws.send(JSON.stringify({ content: message }));
            
            // Clear input
            input.value = '';

            // Input is re-enabled on 'message_end' (after the reply streams in).
            // Safety fallback in case the end frame is lost.
            setTimeout(() => {
                input.disabled = false;
                sendButton.disabled = false;
            }, 60000);
        }
        
        // Enter key to send
        document.getElementById('messageInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
        
        // Mobile tab switching
        function switchTab(tab) {
            document.body.classList.remove('show-chat', 'show-debug');
            document.body.classList.add('show-' + tab);
            const other = tab === 'chat' ? 'debug' : 'chat';
            document.getElementById('tab-' + tab).classList.add('active');
            document.getElementById('tab-' + other).classList.remove('active');
            if (tab === 'debug') {
                document.getElementById('tab-debug').classList.remove('has-new');
            }
        }

        // Connect on load
        connect();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Inbound Telegram updates. Always answers 200 fast; rejects forged calls."""
    settings = get_settings()
    service = get_telegram_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Telegram not configured")
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="bad secret token")

    update = await request.json()
    # Run inline: Telegram tolerates webhook latency and the typing indicator
    # covers the wait. If a turn ever risks the ~60s webhook timeout, switch to
    # asyncio.create_task(service.handle_update(update)) and return immediately.
    await service.handle_update(update)
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time chat and debug info."""
    await websocket.accept()
    
    # Single shared Maya — same companion Telegram talks to (no multi-user).
    sm = get_sessionmaker()
    user_id, companion_id, created, _first = await resolve_singleton(sm)
    if created:
        await send_debug(websocket, "system", "Created new user and companion", {
            "user_id": str(user_id),
            "companion_id": str(companion_id),
        })

    await send_debug(websocket, "system", "Session initialized", {
        "user_id": str(user_id),
        "companion_id": str(companion_id)
    })
    
    # Replay full message history in chronological order
    async with sm() as session:
        stmt = (
            select(Message)
            .where(Message.companion_id == companion_id)
            .order_by(Message.created_at.asc())
        )
        history = list((await session.scalars(stmt)).all())

    for msg in history:
        await websocket.send_json({
            "type": "message",
            "role": msg.role,
            "content": msg.content,
        })

    await websocket.send_json({"type": "history_end"})

    orch = Orchestrator()

    async def on_step(category: str, label: str, data: dict) -> None:
        # The orchestrator emits its own "received" step; skip the echo here.
        await send_debug(websocket, category, label, data)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)
            content = message_data.get("content", "").strip()

            if not content:
                continue

            # Echo user message
            await websocket.send_json({
                "type": "message",
                "role": "user",
                "content": content
            })

            # Stream the assistant reply token-by-token (perceived latency win).
            # message_end is sent the moment the reply finishes streaming —
            # BEFORE post-processing — so the input re-enables immediately and
            # bookkeeping runs in the background of the turn.
            ended = {"sent": False}

            async def send_end(_ended=ended) -> None:
                if not _ended["sent"]:
                    _ended["sent"] = True
                    await websocket.send_json({"type": "message_end"})

            try:
                await websocket.send_json({"type": "message_start", "role": "assistant"})
                async for piece in orch.stream_message(
                    user_id, companion_id, content,
                    on_step=on_step, on_reply_done=lambda _r: send_end(),
                ):
                    await websocket.send_json({"type": "message_chunk", "content": piece})
                await send_end()
            except Exception as e:
                await send_debug(websocket, "error", f"❌ {type(e).__name__}: {e}", {})
                await send_end()
                continue

    except WebSocketDisconnect:
        await send_debug(websocket, "system", "Client disconnected", {})


async def send_debug(websocket: WebSocket, category: str, label: str, data: dict):
    """Send debug info to client."""
    try:
        await websocket.send_json({
            "type": "debug",
            "category": category,
            "label": label,
            "data": data
        })
    except Exception:
        pass  # Client might have disconnected


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
