import asyncio
import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class WebViewConnectionTimeoutException(Exception):
    uri: str | None
    method: str | None
    requestHeaders: Dict | None
    isRedirect: bool | None
    isForMainFrame: bool | None

    def __init__(self, uri, method, requestHeaders, isRedirect, isForMainFrame):
        self.uri = uri
        self.method = method
        self.requestHeaders = requestHeaders
        self.isRedirect = isRedirect
        self.isForMainFrame = isForMainFrame
        super().__init__(f"WebView connection timeout: {self.uri}")


class EventWebViewReceivedException(Exception):
    code: int | None
    msg: str | None
    request: Dict | None

    def __init__(self, data: Dict):
        self.code = data.get("code")
        self.msg = data.get("msg")
        self.request = data.get("request")
        super().__init__(f"code: {self.code}, msg: {self.msg}")

    def convert(self):
        if self.code == -8:
            return WebViewConnectionTimeoutException(**self.request)
        return self


class ClientClosedException(Exception):
    pass


class EventType(str, Enum):
    LOG = "LOG"
    NETWORK_LOG = "NETWORK_LOG"
    DEVICE_INFO = "DEVICE_INFO"
    SETTINGS = "SETTINGS"
    EVALJS = "EVALJS"
    EVALJS_CALLBACK = "EVALJS_CALLBACK"
    EVALJS_FAILURE = "EVALJS_FAILURE"
    COOKIE_REMOVE_ALL = "COOKIE_REMOVE_ALL"
    COOKIE_REMOVE_ALL_CALLBACK = "COOKIE_REMOVE_ALL_CALLBACK"
    COOKIE_REMOVE_ALL_FAILURE = "COOKIE_REMOVE_ALL_FAILURE"
    COOKIE_GET = "COOKIE_GET"
    COOKIE_GET_CALLBACK = "COOKIE_GET_CALLBACK"
    COOKIE_GET_FAILURE = "COOKIE_GET_FAILURE"
    WEBVIEW_PAGE_FINISHED = "WEBVIEW_PAGE_FINISHED"
    WEBVIEW_RECEIVED_ERROR = "WEBVIEW_RECEIVED_ERROR"
    START = "START"
    CLOSE = "CLOSE"


@dataclass
class Event:
    id: str
    type: str
    content: str
    parent_id: str | None

    @classmethod
    def from_json(cls, data: dict) -> "Event":
        return cls(
            id=data["id"],
            type=data["type"],
            content=data["content"],
            parent_id=data.get("parent_id"),
        )

    @property
    def dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "parent_id": self.parent_id,
        }

    @property
    def exception(self):
        #
        if self.type == EventType.WEBVIEW_RECEIVED_ERROR:
            return EventWebViewReceivedException(self.json).convert()
        return None

    @property
    def json(self):
        return json.loads(self.content)


class BaseEventHandler:
    """基础事件处理器"""

    def __init__(self):
        # 注册事件处理方法
        self.handlers = {
            EventType.LOG: self.handle_log,
            EventType.DEVICE_INFO: self.handle_device_info,
            EventType.WEBVIEW_PAGE_FINISHED: self.handle_page_finished,
            EventType.WEBVIEW_RECEIVED_ERROR: self.handle_received_error,
        }

    async def handle_event(self, event: Event) -> Optional[List[Event]]:
        """处理单个事件，返回可选的响应事件列表"""
        handler = self.handlers.get(event.type)
        if handler:
            return await handler(event)
        return None

    async def handle_log(self, event: Event) -> Optional[List[Event]]:
        """处理日志事件"""
        print(f"[LOG] {event.content}")
        return None

    async def handle_device_info(self, event: Event) -> Optional[List[Event]]:
        """处理设备信息事件"""
        print(f"[DEVICE_INFO] Received device info: {event.content}")
        # 这里可以解析和存储设备信息
        return None

    async def handle_page_finished(self, event: Event) -> Optional[List[Event]]:
        """处理页面加载完成事件"""
        print(f"[PAGE_FINISHED] Page loaded: {event.content}")
        return None

    async def handle_received_error(self, event: Event) -> Optional[List[Event]]:
        """处理错误事件"""
        print(f"[ERROR] WebView error: {event.content}")
        return None


class AsyncEventManager:
    """处理事件的异步响应管理"""

    def __init__(self):
        self.pending_requests: Dict[str, asyncio.Future] = {}  # 用于 ID 匹配
        self.pending_type_requests: Dict[str, asyncio.Future] = {}  # 用于类型匹配
        self.hook_events: Dict[str, List[Callable[[str]]]] = {}

    def add_hook(self, event_type: str, callback: Callable[[str], Any]):
        if event_type not in self.hook_events:
            self.hook_events[event_type] = []
        self.hook_events[event_type].append(callback)

    def create_event(self, type: str, content, parent_id: str | None = None) -> Event:
        """创建新的Event对象"""
        if not isinstance(content, str):
            content = json.dumps(content)

        return Event(
            id=str(uuid.uuid4()), type=type, content=content, parent_id=parent_id
        )

    async def wait_for_response(
        self, event_id: str, timeout: float = 0
    ) -> Optional[Event]:
        """等待特定事件的响应"""
        future = asyncio.Future()
        self.pending_requests[event_id] = future
        try:
            if timeout > 0:
                return await asyncio.wait_for(future, timeout)
            else:
                return await future
        except asyncio.TimeoutError:
            print(f"Request {event_id} timed out")
            return None
        finally:
            self.pending_requests.pop(event_id, None)

    async def wait_for_event_type(
        self, *event_types: List[str], timeout: float = 0
    ) -> Optional[Event]:
        """等待特定类型的事件

        Args:
            event_type: 要等待的事件类型
            timeout: 超时时间（秒），0表示永不超时

        Returns:
            Event: 接收到的事件，如果超时则返回None
        """
        future = asyncio.Future()
        for event_type in event_types:
            self.pending_type_requests[event_type] = future

        try:
            if timeout > 0:
                return await asyncio.wait_for(future, timeout)
            else:
                return await future
        except asyncio.TimeoutError:
            print(f"Waiting for event type {event_type} timed out")
            return None
        finally:
            for event_type in event_types:
                self.pending_type_requests.pop(event_type, None)

    def handle_response(self, event: Event):
        """处理响应事件

        Returns:
            bool: 如果事件被处理则返回True，否则返回False
        """
        # 检查是否匹配ID
        if event.parent_id and event.parent_id in self.pending_requests:
            future = self.pending_requests[event.parent_id]
            if not future.done():
                future.set_result(event)

        # 检查是否匹配类型
        if event.type in self.pending_type_requests:
            future = self.pending_type_requests[event.type]
            if not future.done():
                future.set_result(event)

        # 检查是否匹配hook
        if event.type in self.hook_events:
            for hook in self.hook_events[event.type]:
                hook(event.content)

    def on_ws_closed(self):
        for futuer in self.pending_requests.values():
            futuer.set_exception(ClientClosedException())
        for futuer in self.pending_type_requests.values():
            futuer.set_exception(ClientClosedException())
