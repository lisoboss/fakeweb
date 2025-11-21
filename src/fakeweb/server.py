import asyncio
import json
import traceback
from datetime import datetime
from typing import Dict, List

import websockets.asyncio.server
from websockets.asyncio.server import ServerConnection

from .event import *


class WebSocketServer:
    """基础WebSocket服务器"""

    hook_client: Optional[Callable[[ServerConnection], None]] = None

    def __init__(self):
        self.clients: Dict[ServerConnection, dict] = {}
        self.event_handler = BaseEventHandler()
        self.event_manager: Dict[ServerConnection, AsyncEventManager] = {}

    async def handle_message(self, websocket: ServerConnection, events: List[Event]):
        """处理接收到的消息"""
        for event in events:
            print(f"Received event: {event.type} with content: {len(event.content)}")
            # 检查是否是对某个请求的响应
            self.event_manager[websocket].handle_response(event)
            responses = await self.event_handler.handle_event(event)
            if responses:
                # 如果有响应，发送回客户端
                await websocket.send(json.dumps([r.to_dict() for r in responses]))

    async def update_info(
        self, websocket: ServerConnection, asyncEventManager: AsyncEventManager
    ):
        info_event = await asyncEventManager.wait_for_event_type(EventType.DEVICE_INFO)
        info = json.loads(info_event.content)
        self.clients[websocket] = info
        print(f"New client connected: {websocket} {info}")
        if self.hook_client:
            self.hook_client(websocket)

    async def handle_client(self, websocket: ServerConnection):
        """处理客户端连接"""
        asyncEventManager = AsyncEventManager()
        self.event_manager[websocket] = asyncEventManager
        try:
            asyncio.get_event_loop().create_task(
                self.update_info(websocket, asyncEventManager)
            )

            async for message in websocket:
                try:
                    data = json.loads(message)
                    if not isinstance(data, list):
                        print(
                            f"Invalid message format - expected list, got: {type(data)}"
                        )
                        continue

                    events = [Event.from_json(event_data) for event_data in data]
                    await self.handle_message(websocket, events)

                except json.JSONDecodeError:
                    print(f"Invalid JSON received: {message}")
                except Exception as e:
                    print(f"Error processing message: {str(e)}")
                    print(self._format_exception(e))

        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {self.clients[websocket]}")
        finally:
            asyncEventManager.on_ws_closed()
            if websocket in self.clients:
                del self.clients[websocket]

    async def start(self):
        await websockets.asyncio.server.serve(self.handle_client, "192.168.2.35", 8080)
        print("WebSocket server started on ws://192.168.2.35:8080")

    def _format_exception(self, e: Exception) -> str:
        """格式化异常信息"""
        return f"""
Exception Type: {type(e).__name__}
Exception Message: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Traceback:
{''.join(traceback.format_tb(e.__traceback__))}
        """
