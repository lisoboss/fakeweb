import json
from typing import Callable, Set

from websockets.asyncio.server import ServerConnection

from .event import *
from .server import *


class FakeBrowserManager:

    def __init__(self):
        self.server = WebSocketServer()
        self._task = asyncio.create_task(self.server.start())

    def browsers(self):
        return self.server.clients

    def create_fake_browser(self, websocket: ServerConnection):
        return FakeBrowser(
            self.server.clients[websocket].get("device_id"),
            self.server.event_manager[websocket],
            lambda *events: websocket.send(
                json.dumps([event.dict for event in events])
            ),
        )


class AllFakeBrowserManager(FakeBrowserManager):

    def __init__(self):
        super().__init__()
        self._new_clients: Set[ServerConnection] = set()
        self._client_event = asyncio.Event()
        self.server.hook_client = self.hook_client

    def hook_client(self, websocket: ServerConnection):
        self._new_clients.add(websocket)
        self._client_event.set()

    async def accept(self):
        await self._client_event.wait()
        self._client_event.clear()
        return self._new_clients.pop()


class Element:
    eid: str

    def __init__(self, eid: str):
        self.eid = eid.strip().strip('"').strip("'")

    def __str__(self):
        return f"<{self.__module__}.{self.__class__.__name__}({self.eid}) object at 0x{id(self):X}>"


class FakeBrowser:
    """高级协议封装"""

    def __init__(
        self, device_id: str, event_manager: AsyncEventManager, send_callback: Callable
    ):
        self.device_id = device_id
        self._event_manager = event_manager
        self._send_callback = send_callback
        self._start_url = ""

    def __str__(self):
        return f"<{self.__module__}.{self.__class__.__name__}({self.device_id}) object at 0x{id(self):X}>"

    def _create_event(self, type: str, content, parent_id: str | None = None) -> Event:
        return self._event_manager.create_event(
            type=type,
            content=content,
            parent_id=parent_id,
        )

    def hook_network(self, callback: Callable[[str], Any]):
        self._event_manager.add_hook(EventType.NETWORK_LOG, callback)

    async def settings(self, ua: str, pkname: str = "", proxies: str = ""):
        """
        config: {
            "fakeWebViewPackageName": "",
            "fakeUserAgentString": "",
            # support socks,http,https
            "fakeProxies": "",
        }
        """
        await self._send_callback(
            self._create_event(
                EventType.SETTINGS,
                {
                    "fakeUserAgentString": ua,
                    "fakeWebViewPackageName": pkname,
                    "fakeProxies": proxies,
                },
            )
        )

    async def start(self, url: str):
        self._start_url = url
        await self._send_callback(
            self._create_event(EventType.SETTINGS, {"fakeLoadUrl": url})
        )
        await self._send_callback(self._create_event(EventType.START, ""))

    async def close(self):
        await self._send_callback(self._create_event(EventType.CLOSE, ""))

    async def loaded(self, timeout: float = 0):
        while True:
            event: Event = await self._event_manager.wait_for_event_type(
                EventType.WEBVIEW_PAGE_FINISHED,
                EventType.WEBVIEW_RECEIVED_ERROR,
                timeout=timeout,
            )
            if event.type == EventType.WEBVIEW_PAGE_FINISHED:
                break
            if event.type == EventType.WEBVIEW_RECEIVED_ERROR:
                e = event.exception
                if isinstance(e, WebViewConnectionTimeoutException):
                    if e.uri.startswith(self._start_url):
                        raise e

    async def loaded_raise(self, timeout: float = 0):
        while True:
            event: Event = await self._event_manager.wait_for_event_type(
                EventType.WEBVIEW_PAGE_FINISHED,
                EventType.WEBVIEW_RECEIVED_ERROR,
                timeout=timeout,
            )
            if event.type == EventType.WEBVIEW_PAGE_FINISHED:
                break
            if event.type == EventType.WEBVIEW_RECEIVED_ERROR:
                raise event.exception

    async def execute_js(self, js_code: str, timeout: float = 0) -> Optional[str]:
        """执行JavaScript代码并等待响应"""
        # 创建EVALJS事件
        event = self._create_event(EventType.EVALJS, js_code)

        # 发送事件
        await self._send_callback(event)

        # 等待响应
        response = await self._event_manager.wait_for_response(
            event.id, timeout=timeout
        )

        if response:
            if response.type == EventType.EVALJS_CALLBACK:
                return response.content
            elif response.type == EventType.EVALJS_FAILURE:
                raise Exception(f"JavaScript execution failed: {response.content}")
        return None

    async def querySelector(self, selectors: str) -> Optional[Element]:
        js_code = f"""(function(selectors){{
            const ele = document.querySelector(selectors)
            if (ele) return window.__FEC.set(ele)
            return null
        }})({repr(selectors)})"""
        eid = await self.execute_js(js_code)
        if eid and eid != "null":
            return Element(eid)

    async def click(self, x: int, y: int, element: Element):
        js_code = f"""(function(x, y, eid){{
            const ele = window.__FEC.get(eid)
            if (ele) {{
                const event = new MouseEvent('click', {{
                    'view': window,
                    'bubbles': true,
                    'cancelable': true,
                    'clientX': x,
                    'clientY': y
                }})
                ele.dispatchEvent(event)
            }}
        }})({x}, {y}, {repr(element.eid)})"""
        await self.execute_js(js_code)

    async def remove_all_cookies(self, timeout: float = 0):
        """删除所有Cookie"""
        # 创建remove cookies 事件
        event = self._create_event(EventType.COOKIE_REMOVE_ALL, "")

        # 发送事件
        await self._send_callback(event)

        # 等待响应
        response = await self._event_manager.wait_for_response(
            event.id, timeout=timeout
        )

        if response:
            if response.type == EventType.COOKIE_REMOVE_ALL_CALLBACK:
                return response.content
            elif response.type == EventType.COOKIE_REMOVE_ALL_FAILURE:
                raise Exception(f"Remove all cookies failed: {response.content}")

        return None

    async def get_cookies(self, url: str, timeout: float = 0) -> Optional[str]:
        """获取Cookie"""
        # 创建get cookies 事件
        event = self._create_event(EventType.COOKIE_GET, url)

        # 发送事件
        await self._send_callback(event)

        # 等待响应
        response = await self._event_manager.wait_for_response(
            event.id, timeout=timeout
        )

        if response:
            if response.type == EventType.COOKIE_GET_CALLBACK:
                return response.content
            elif response.type == EventType.COOKIE_GET_FAILURE:
                raise Exception(f"Get cookies failed: {response.content}")
        return None
