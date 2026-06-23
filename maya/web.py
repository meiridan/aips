"""Simple web UI for Maya with debug flow visualization."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from maya.config import get_settings
from maya.conversation.orchestrator import MEMORY_LIMIT, RECENT_LIMIT, Orchestrator
from maya.db.models import Companion, Message, User
from maya.db.session import get_sessionmaker
from maya.logging import configure_logging

app = FastAPI(title="Maya Web UI")


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
            
            // Re-enable after a moment
            setTimeout(() => {
                input.disabled = false;
                sendButton.disabled = false;
                input.focus();
            }, 500);
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time chat and debug info."""
    await websocket.accept()
    
    # Get or create test user/companion
    sm = get_sessionmaker()
    async with sm() as session:
        # Try to get existing user
        from sqlalchemy import select
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        
        if not user:
            # Create test user
            user = User(name="Web User", description="Testing via web UI")
            session.add(user)
            await session.flush()
            
            companion = Companion(user_id=user.id, name="Maya", template_id="flirt")
            session.add(companion)
            await session.commit()
            
            await send_debug(websocket, "system", "Created new user and companion", {
                "user_id": str(user.id),
                "companion_id": str(companion.id)
            })
        else:
            # Get first companion
            result = await session.execute(
                select(Companion).where(Companion.user_id == user.id).limit(1)
            )
            companion = result.scalar_one_or_none()
            
            if not companion:
                companion = Companion(user_id=user.id, name="Maya", template_id="flirt")
                session.add(companion)
                await session.commit()
    
    user_id = user.id
    companion_id = companion.id
    
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

    orch = DebugOrchestrator(websocket)

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
            
            await send_debug(websocket, "step", "📥 Received user message", {
                "content": content[:100] + ("..." if len(content) > 100 else "")
            })

            try:
                # Process message with debug info
                response = await orch.handle_message(user_id, companion_id, content)
            except Exception as e:
                await send_debug(websocket, "error", f"❌ {type(e).__name__}: {e}", {})
                continue

            # Send assistant response
            await websocket.send_json({
                "type": "message",
                "role": "assistant",
                "content": response
            })
            
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


class DebugOrchestrator(Orchestrator):
    """Orchestrator with debug output."""
    
    def __init__(self, websocket: WebSocket):
        super().__init__()
        self.websocket = websocket
    
    async def handle_message(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        content: str,
    ) -> str:
        """Handle message with debug output at each step."""
        import asyncio as _asyncio
        import time
        
        async with self._sessionmaker() as session:
            # Step 1: Save user message
            await send_debug(self.websocket, "step", "💾 Saving user message to database", {
                "user_id": str(user_id),
                "companion_id": str(companion_id)
            })
            
            await self._save_message(session, companion_id, user_id, "user", content)
            await session.commit()
            
            await send_debug(self.websocket, "step", "✅ User message saved", {})
            
            # Step 2a: Search memory (with timing for latency visibility)
            await send_debug(self.websocket, "memory", "🧠 Searching long-term memory (semantic / pgvector)", {
                "query": content[:80]
            })

            _mem_start = time.time()
            memories_task = self.memory.search_relevant(
                query=content, user_id=user_id, companion_id=companion_id, limit=MEMORY_LIMIT
            )
            recent_task = self._recent_messages(session, companion_id, RECENT_LIMIT)
            memories, recent = await _asyncio.gather(memories_task, recent_task)
            _mem_latency_ms = int((time.time() - _mem_start) * 1000)

            await send_debug(self.websocket, "memory", f"✅ Retrieved {len(memories)} memories ({_mem_latency_ms}ms)", {
                "search_latency_ms": _mem_latency_ms,
                "memories": [
                    {
                        "text": m["text"],
                        "score": round(m.get("score"), 3) if isinstance(m.get("score"), (int, float)) else None,
                    }
                    for m in memories
                ] if memories else "(no memories yet)"
            })
            
            # Step 2b: Get recent messages
            await send_debug(self.websocket, "step", f"📚 Retrieved last {len(recent)} messages", {
                "message_count": len(recent),
                "preview": [
                    {"role": m.role, "content": m.content[:60] + ("..." if len(m.content) > 60 else "")}
                    for m in recent[-5:]
                ]
            })
            
            # Step 3: Build prompt
            from maya.conversation.prompt_builder import (
                SYSTEM_PROMPT_TEMPLATE,
                format_memories,
            )
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                memories=format_memories(memories)
            )
            
            await send_debug(self.websocket, "step", "🔨 Built prompt with memories injected", {
                "system_prompt_preview": system_prompt[:300] + ("..." if len(system_prompt) > 300 else ""),
                "context_messages": len(recent),
                "memories_in_context": len(memories)
            })
            
            prompt = [{"role": "system", "content": system_prompt}]
            prompt += [{"role": m.role, "content": m.content} for m in recent]
            
            # Step 4: Call LLM
            await send_debug(self.websocket, "llm", "🤖 Calling LLM (Grok-3)", {
                "model_tier": "main",
                "total_messages": len(prompt)
            })
            
            start = time.time()
            
            try:
                response = await self.llm.chat(prompt, model_tier="main")
                elapsed = time.time() - start
                
                await send_debug(self.websocket, "llm", "✅ LLM response received", {
                    "latency_ms": int(elapsed * 1000),
                    "response_preview": response[:120] + ("..." if len(response) > 120 else "")
                })
            except Exception as e:
                await send_debug(self.websocket, "error", "❌ LLM call failed", {
                    "error": str(e)
                })
                raise
            
            # Step 5: Save assistant message
            await self._save_message(
                session, companion_id, user_id, "assistant", response
            )
            await session.commit()
            
            await send_debug(self.websocket, "step", "✅ Assistant response saved", {})
        
        # Step 6: Extract memories — awaited so facts persist before next turn
        await send_debug(self.websocket, "memory", "🔍 Extracting facts from this exchange", {
            "user_message": content[:80],
            "assistant_message": response[:80]
        })
        try:
            facts = await self.memory.extract_and_store(
                user_id=user_id,
                companion_id=companion_id,
                user_message=content,
                assistant_message=response,
            )
            if facts:
                await send_debug(self.websocket, "memory", f"💡 Extracted {len(facts)} new fact(s)", {
                    "new_facts": facts
                })
            else:
                await send_debug(self.websocket, "memory", "💡 No new facts to remember", {})
        except Exception as e:
            await send_debug(self.websocket, "error", "❌ Memory extraction failed", {
                "error": str(e)
            })

        await send_debug(self.websocket, "step", "🎉 Message handling complete", {})
        
        return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
