import asyncio
import json
import os
import sys
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_utils import get_client_ssl_context
from protocol import async_recv_framed, async_send_framed

HOST = "127.0.0.1"
TCP_PORT = 4000
WS_PORT = 8080

app = FastAPI(title="MediQueue Connect WebSocket Gateway", version="1.0.0")


@app.get("/")
async def root():
    return {
        "service": "MediQueue Connect WebSocket Gateway Bridge",
        "status": "online",
        "websocket_endpoint": f"ws://{HOST}:{WS_PORT}/ws"
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Establish TCP client connection to Health Server
    ssl_ctx = None
    try:
        ssl_ctx = get_client_ssl_context()
    except Exception:
        ssl_ctx = None

    try:
        reader, writer = await asyncio.open_connection(HOST, TCP_PORT, ssl=ssl_ctx)
    except Exception:
        # Fallback to plain TCP if SSL handshake fails
        try:
            reader, writer = await asyncio.open_connection(HOST, TCP_PORT)
        except Exception as e:
            await websocket.send_json({"status": "ERROR", "reason": f"Cannot connect to Health Server: {e}"})
            await websocket.close()
            return

    try:
        while True:
            data_str = await websocket.receive_text()
            try:
                payload = json.loads(data_str)
            except Exception:
                await websocket.send_json({"status": "ERROR", "reason": "Invalid JSON format"})
                continue

            # Forward frame to TCP Health Server
            await async_send_framed(writer, payload)

            # Read framed response from TCP Health Server
            response = await async_recv_framed(reader)
            if response is None:
                await websocket.send_json({"status": "ERROR", "reason": "Health Server disconnected"})
                break

            # Return response frame to WebSocket client
            await websocket.send_json(response)

    except WebSocketDisconnect:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=WS_PORT)
