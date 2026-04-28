# -*- coding: utf-8 -*-
"""
消息模型层：MsgSeg / MsgChain / Message
不可变数据结构，支持序列化与反序列化
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union


if TYPE_CHECKING:
    from PIL import Image as PILImage
    _HAS_PIL = True
else:
    try:
        from PIL import Image as PILImage
        _HAS_PIL = True
    except ImportError:
        PILImage = None
        _HAS_PIL = False

from fcatbot.core.client import (
    FileInfo,
    FileUrl,
    ImageInfo,
    MessageData,
    MessageInfo,
    NapCatApiError,
    NapCatClient,
    RecordInfo,
    SenderInfo,
    get_api,
)


# ==================== 消息段 ====================

class MsgSeg:
    def __init__(self, type_: str, data: Dict[str, Any]) -> None:
        self.type: str = type_
        self.data: Dict[str, Any] = data

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "data": {k: v for k, v in self.data.items() if v is not None}}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.data})"


class TextSeg(MsgSeg):
    def __init__(self, text: str) -> None:
        super().__init__("text", {"text": text})
        self.text: str = text

    def __str__(self) -> str:
        return self.text


class AtSeg(MsgSeg):
    def __init__(self, qq: Union[int, str]) -> None:
        super().__init__("at", {"qq": str(qq)})
        self.qq: str = str(qq)


class FaceSeg(MsgSeg):
    def __init__(self, id: Union[int, str]) -> None:
        super().__init__("face", {"id": str(id)})
        self.id: str = str(id)


class ReplySeg(MsgSeg):
    def __init__(self, id: Union[int, str]) -> None:
        super().__init__("reply", {"id": str(id)})
        self.id: str = str(id)

    async def fetch_source(self, api: Optional[NapCatClient] = None) -> MessageInfo:
        a = api or get_api()
        raw = await a.get_msg(self.id)
        if isinstance(raw, dict):
            return MessageInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取消息详情失败")


def _normalize_image_input(
    file: Union[str, "PILImage.Image", bytes, io.BytesIO, pathlib.Path]
) -> str:
    if isinstance(file, str):
        return file
    if isinstance(file, pathlib.Path):
        return str(file)
    if _HAS_PIL and isinstance(file, PILImage.Image):
        buf = io.BytesIO()
        fmt = file.format or "PNG"
        file.save(buf, format=fmt)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"base64://{b64}"
    if isinstance(file, bytes):
        b64 = base64.b64encode(file).decode("ascii")
        return f"base64://{b64}"
    if isinstance(file, io.BytesIO):
        b64 = base64.b64encode(file.getvalue()).decode("ascii")
        return f"base64://{b64}"
    raise TypeError(f"不支持的图片类型: {type(file).__name__}")


class ImageSeg(MsgSeg):
    def __init__(
        self,
        file: Union[str, "PILImage.Image", bytes, io.BytesIO, pathlib.Path],
        name: Optional[str] = None,
        summary: Optional[str] = None,
        sub_type: Optional[int] = None,
        **extra: Any,
    ) -> None:
        file_str = _normalize_image_input(file)
        data: Dict[str, Any] = {"file": file_str}
        if name is not None:
            data["name"] = name
        if summary is not None:
            data["summary"] = summary
        if sub_type is not None:
            data["sub_type"] = sub_type
        data.update(extra)
        super().__init__("image", data)
        self.file: str = file_str

    async def fetch(self, api: Optional[NapCatClient] = None) -> ImageInfo:
        a = api or get_api()
        raw = await a.get_image(file=self.file)
        if isinstance(raw, dict):
            return ImageInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取图片信息失败")


class RecordSeg(MsgSeg):
    def __init__(self, file: str, name: Optional[str] = None) -> None:
        data: Dict[str, Any] = {"file": file}
        if name:
            data["name"] = name
        super().__init__("record", data)
        self.file: str = file

    async def fetch(
        self, api: Optional[NapCatClient] = None, out_format: str = "mp3"
    ) -> RecordInfo:
        a = api or get_api()
        raw = await a.get_record(file=self.file, out_format=out_format)
        if isinstance(raw, dict):
            return RecordInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取语音信息失败")


class VideoSeg(MsgSeg):
    def __init__(self, file: str, thumb: Optional[str] = None) -> None:
        data: Dict[str, Any] = {"file": file}
        if thumb:
            data["thumb"] = thumb
        super().__init__("video", data)
        self.file: str = file

    async def fetch(self, api: Optional[NapCatClient] = None) -> FileInfo:
        a = api or get_api()
        raw = await a.get_file(file=self.file)
        if isinstance(raw, dict):
            return FileInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取视频信息失败")


class FileSeg(MsgSeg):
    def __init__(self, file: str, name: Optional[str] = None) -> None:
        data: Dict[str, Any] = {"file": file}
        if name:
            data["name"] = name
        super().__init__("file", data)
        self.file: str = file

    async def fetch(self, api: Optional[NapCatClient] = None) -> FileInfo:
        a = api or get_api()
        raw = await a.get_file(file=self.file)
        if isinstance(raw, dict):
            return FileInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取文件信息失败")

    async def get_url(
        self,
        api: Optional[NapCatClient] = None,
        group_id: Optional[Union[int, str]] = None,
    ) -> str:
        a = api or get_api()
        if group_id is not None:
            raw = await a.get_group_file_url(self.file, group_id)
        else:
            raw = await a.get_private_file_url(self.file)
        if isinstance(raw, dict):
            return FileUrl.from_dict(raw).url
        raise NapCatApiError(-1, "获取文件链接失败")


_SEG_MAP: Dict[str, Callable[[Dict[str, Any]], MsgSeg]] = {
    "text": lambda d: TextSeg(d["text"]),
    "at": lambda d: AtSeg(d["qq"]),
    "image": lambda d: ImageSeg(**d),
    "record": lambda d: RecordSeg(d["file"], d.get("name")),
    "video": lambda d: VideoSeg(d["file"], d.get("thumb")),
    "file": lambda d: FileSeg(d["file"], d.get("name")),
    "reply": lambda d: ReplySeg(d["id"]),
    "face": lambda d: FaceSeg(d["id"]),
}


def _coerce_seg(item: Union[MsgSeg, str]) -> MsgSeg:
    if isinstance(item, str):
        return TextSeg(item)
    if isinstance(item, MsgSeg):
        return item
    raise TypeError(f"不能加入消息链的类型: {type(item).__name__}")


# ==================== 消息链 ====================

class MsgChain(Sequence):
    __slots__ = ("_nodes",)

    def __init__(self, nodes: Optional[Iterable[Union[MsgSeg, str]]] = None) -> None:
        self._nodes: Tuple[Union[MsgSeg, str], ...] = tuple(
            _coerce_seg(n) for n in (nodes or ())
        )

    def __getitem__(self, index: Union[int, slice]) -> Union[MsgSeg, str, MsgChain]:
        if isinstance(index, slice):
            return MsgChain(self._nodes[index])
        return self._nodes[index]

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[Union[MsgSeg, str]]:
        return iter(self._nodes)

    def __repr__(self) -> str:
        return f"MsgChain({list(self._nodes)!r})"

    def __str__(self) -> str:
        return "".join(str(n) for n in self._nodes)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, MsgChain) and self._nodes == other._nodes

    def __hash__(self) -> int:
        return hash(self._nodes)

    def __add__(
        self, other: Union[MsgSeg, str, MsgChain, Iterable[Union[MsgSeg, str]]]
    ) -> MsgChain:
        if isinstance(other, MsgChain):
            return MsgChain(self._nodes + other._nodes)
        return MsgChain(list(self._nodes) + [_coerce_seg(other)])

    @classmethod
    def empty(cls) -> MsgChain:
        return cls()

    @classmethod
    def of(cls, *nodes: Union[MsgSeg, str]) -> MsgChain:
        return cls(nodes)

    @classmethod
    def from_text(cls, text: str) -> MsgChain:
        return cls([text])

    @classmethod
    def from_arr(cls, arr: List[Dict[str, Any]]) -> MsgChain:
        nodes: List[MsgSeg] = []
        for item in arr:
            t = item.get("type")
            d = item.get("data", {})
            if t in _SEG_MAP:
                try:
                    nodes.append(_SEG_MAP[t](d))
                except Exception:
                    nodes.append(MsgSeg(t, d))
            else:
                nodes.append(MsgSeg(t, d))
        return cls(nodes)

    @classmethod
    def from_json(cls, s: str) -> MsgChain:
        return cls.from_arr(json.loads(s))

    def to_arr(self) -> List[Dict[str, Any]]:
        return [seg.to_dict() for seg in self._nodes if isinstance(seg, MsgSeg)]

    def to_json(self, ensure_ascii: bool = False) -> str:
        return json.dumps(self.to_arr(), ensure_ascii=ensure_ascii)

    def find(self, type_: str) -> List[MsgSeg]:
        return [s for s in self._nodes if isinstance(s, MsgSeg) and s.type == type_]

    def first(self, type_: str) -> Optional[MsgSeg]:
        for s in self._nodes:
            if isinstance(s, MsgSeg) and s.type == type_:
                return s
        return None

    def has(self, type_: str) -> bool:
        return any(isinstance(s, MsgSeg) and s.type == type_ for s in self._nodes)

    def filter(self, predicate: Callable[[Union[MsgSeg, str]], bool]) -> MsgChain:
        return MsgChain(n for n in self._nodes if predicate(n))

    def find_first(
        self, predicate: Callable[[Union[MsgSeg, str]], bool]
    ) -> Union[MsgSeg, str, None]:
        for n in self._nodes:
            if predicate(n):
                return n
        return None

    def get_texts(self) -> List[str]:
        return [n for n in self._nodes if isinstance(n, str)]

    def get_segments(self) -> List[MsgSeg]:
        return [n for n in self._nodes if isinstance(n, MsgSeg)]

    def plain_text(self) -> str:
        parts: List[str] = []
        for s in self._nodes:
            if isinstance(s, TextSeg):
                parts.append(s.text)
            elif isinstance(s, AtSeg):
                parts.append(f"@{s.qq}")
            elif isinstance(s, FaceSeg):
                parts.append(f"[表情:{s.id}]")
            elif isinstance(s, ImageSeg):
                parts.append(s.data.get("summary", "[图片]"))
        return "".join(parts)

    async def send_group(
        self, group_id: Union[int, str], api: Optional[NapCatClient] = None
    ) -> MessageData:
        a = api or get_api()
        raw = await a.send_group_msg(message=self.to_arr(), group_id=group_id)
        if isinstance(raw, dict):
            return MessageData.from_dict(raw)
        raise NapCatApiError(-1, "发送群消息失败")

    async def send_private(
        self, user_id: Union[int, str], api: Optional[NapCatClient] = None
    ) -> MessageData:
        a = api or get_api()
        raw = await a.send_private_msg(message=self.to_arr(), user_id=user_id)
        if isinstance(raw, dict):
            return MessageData.from_dict(raw)
        raise NapCatApiError(-1, "发送私聊消息失败")


# ==================== 引用元信息 ====================

@dataclass(frozen=True)
class MessageReference:
    message_id: str
    sender_id: str
    preview: str
    timestamp: int

    async def fetch_message(self, api: Optional[NapCatClient] = None) -> Optional[Message]:
        a = api or get_api()
        try:
            raw = await a.get_msg(self.message_id)
            if isinstance(raw, dict):
                return Message(raw)
            return None
        except Exception:
            return None


# ==================== 消息实体 ====================

class Message:
    Normal = "normal"
    Reply = "reply"
    Forward = "forward"
    System = "system"

    __slots__ = ("_raw", "_chain", "_reference", "_message_type", "_api")

    def __init__(self, event: Dict[str, Any]) -> None:
        self._raw: Dict[str, Any] = event
        self._chain: Optional[MsgChain] = None
        self._reference: Optional[MessageReference] = None
        self._message_type: Optional[str] = None
        self._api: NapCatClient = get_api()

    @property
    def id(self) -> int:
        return int(self._raw.get("message_id", 0))

    @property
    def sender_id(self) -> int:
        return int(self._raw.get("user_id", 0))

    @property
    def chain(self) -> MsgChain:
        if self._chain is None:
            self._chain = MsgChain.from_arr(self._raw.get("message", []))
        return self._chain

    @property
    def timestamp(self) -> int:
        return int(self._raw.get("time", 0))

    @property
    def group_id(self) -> Optional[int]:
        gid = self._raw.get("group_id")
        return int(gid) if gid is not None else None

    @property
    def raw_message(self) -> str:
        return self._raw.get("raw_message", "")

    @property
    def raw(self) -> Dict[str, Any]:
        return self._raw

    @property
    def is_group(self) -> bool:
        return self.group_id is not None

    @property
    def is_private(self) -> bool:
        return self.group_id is None

    @property
    def message_type(self) -> str:
        if self._message_type is None:
            self._message_type = self._detect_type()
        return self._message_type

    def _detect_type(self) -> str:
        if self.chain.has("reply"):
            return self.Reply
        if self.chain.has("forward"):
            return self.Forward
        raw_msg_type = self._raw.get("raw", {}).get("msgType")
        if raw_msg_type in (5, 33):
            return self.System
        return self.Normal

    @property
    def is_reply(self) -> bool:
        return self.message_type == self.Reply

    @property
    def is_forward(self) -> bool:
        return self.message_type == self.Forward

    @property
    def is_system(self) -> bool:
        return self.message_type == self.System

    @property
    def is_normal(self) -> bool:
        return self.message_type == self.Normal

    @property
    def reference(self) -> Optional[MessageReference]:
        if self._reference is None and self.is_reply:
            self._reference = self._extract_reference()
        return self._reference

    def _extract_reference(self) -> Optional[MessageReference]:
        elements = self._raw.get("raw", {}).get("elements", [])
        reply_elem: Optional[Dict[str, Any]] = None
        for elem in elements:
            if elem.get("elementType") == 7 and elem.get("replyElement"):
                reply_elem = elem["replyElement"]
                break
        if not reply_elem:
            return None
        text_elems = reply_elem.get("sourceMsgTextElems", [])
        preview = ""
        for te in text_elems:
            if te.get("replyAbsElemType") == 1:
                preview += te.get("textElemContent", "")
        return MessageReference(
            message_id=reply_elem.get("sourceMsgIdInRecords", ""),
            sender_id=reply_elem.get("senderUid", ""),
            preview=preview[:50],
            timestamp=int(reply_elem.get("replyMsgTime", "0"))
            if str(reply_elem.get("replyMsgTime", "0")).isdigit()
            else 0,
        )

    @property
    def sender(self) -> SenderInfo:
        return SenderInfo.from_dict(self._raw.get("sender", {}))

    def __getitem__(self, index: Union[int, slice]) -> Union[MsgSeg, str, MsgChain]:
        return self.chain[index]

    def __len__(self) -> int:
        return len(self.chain)

    def __iter__(self) -> Iterator[Union[MsgSeg, str]]:
        return iter(self.chain)

    def __contains__(self, item: Any) -> bool:
        return item in self.chain

    def __repr__(self) -> str:
        return (
            f"Message(id={self.id}, type={self.message_type}, "
            f"sender={self.sender_id}, group={self.group_id})"
        )

    def __str__(self) -> str:
        return self.chain.plain_text()

    async def reply(self, chain: MsgChain) -> MessageData:
        reply_chain = MsgChain.of(ReplySeg(self.id)) + chain
        if self.is_group:
            assert self.group_id is not None
            raw = await self._api.send_group_msg(
                message=reply_chain.to_arr(), group_id=self.group_id
            )
        else:
            raw = await self._api.send_private_msg(
                message=reply_chain.to_arr(), user_id=self.sender_id
            )
        if isinstance(raw, dict):
            return MessageData.from_dict(raw)
        raise NapCatApiError(-1, "回复消息失败")

    async def reply_text(self, text: str) -> MessageData:
        return await self.reply(MsgChain.from_text(text))

    async def delete(self) -> None:
        await self._api.delete_msg(self.id)

    async def fetch_source(self) -> Optional[Message]:
        if self.reference:
            return await self.reference.fetch_message(self._api)
        return None

    async def reply_at(self, chain: MsgChain) -> MessageData:
        reply_chain = MsgChain.of(ReplySeg(self.id), AtSeg(self.sender_id)) + chain
        if self.is_group:
            assert self.group_id is not None
            raw = await self._api.send_group_msg(
                message=reply_chain.to_arr(), group_id=self.group_id
            )
        else:
            raw = await self._api.send_private_msg(
                message=reply_chain.to_arr(), user_id=self.sender_id
            )
        if isinstance(raw, dict):
            return MessageData.from_dict(raw)
        raise NapCatApiError(-1, "回复并@失败")

    @classmethod
    def from_event(cls, event: Dict[str, Any]) -> Message:
        return cls(event)