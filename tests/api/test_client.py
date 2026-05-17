"""Tests for API client module."""

from typing import Any, Dict

import pytest

from fcatbot.api.client import APIClient, ApiRequest

# ---------- ApiRequest Tests ----------


class TestApiRequest:
    def test_request_creation(self):
        req = ApiRequest(activity="test_action", data={"key": "value"})
        assert req.activity == "test_action"
        assert req.data == {"key": "value"}
        assert req.headers is None

    def test_request_defaults(self):
        req = ApiRequest(activity="test")
        assert req.data == {}
        assert req.headers is None

    def test_request_with_headers(self):
        req = ApiRequest(
            activity="test", data={}, headers={"Authorization": "Bearer token"}
        )
        assert req.headers == {"Authorization": "Bearer token"}

    def test_request_equality(self):
        req1 = ApiRequest(activity="test", data={"a": 1})
        req2 = ApiRequest(activity="test", data={"a": 1})
        assert req1 == req2

    def test_request_inequality(self):
        req1 = ApiRequest(activity="test1")
        req2 = ApiRequest(activity="test2")
        assert req1 != req2

    def test_request_repr(self):
        req = ApiRequest("test_action")
        r = repr(req)
        assert "test_action" in r
        assert "ApiRequest" in r


# ---------- Concrete API Implementation Tests ----------


class EchoAPI(APIClient[str]):
    """Concrete API implementation for testing."""

    async def invoke(self, request: ApiRequest) -> str:
        return f"[{request.activity}] {request.data}"


class DictAPI(APIClient[Dict]):
    """API that returns dicts."""

    async def invoke(self, request: ApiRequest) -> Dict:
        return {"activity": request.activity, "data": request.data}


class TestConcreteAPI:
    @pytest.mark.asyncio
    async def test_echo_api(self):
        api = EchoAPI()
        result = await api.call("test", {"a": 1})
        assert result == "[test] {'a': 1}"

    @pytest.mark.asyncio
    async def test_echo_api_empty_data(self):
        api = EchoAPI()
        result = await api.call("test")
        assert result == "[test] {}"

    @pytest.mark.asyncio
    async def test_dict_api(self):
        api = DictAPI()
        result = await api.call("send_message", {"text": "hello"})
        assert result["activity"] == "send_message"
        assert result["data"]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_api_with_headers(self):
        captured_headers = {}

        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                captured_headers.update(request.headers or {})
                return "ok"

        api = MyAPI()
        result = await api.call(
            "action", {}, headers={"Authorization": "Bearer token123"}
        )
        assert result == "ok"
        assert captured_headers["Authorization"] == "Bearer token123"


# ---------- Dispatch Tests ----------


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_api_request(self):
        """Test that _dispatch_result handles ApiRequest return."""

        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return f"result:{request.activity}"

        api = MyAPI()
        req = ApiRequest("nested_action")
        result = await api._dispatch_result(req)
        assert result == "result:nested_action"

    @pytest.mark.asyncio
    async def test_dispatch_string(self):
        """Test that _dispatch_result handles string return."""

        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return f"str:{request.activity}"

        api = MyAPI()
        result = await api._dispatch_result("direct_action")
        assert result == "str:direct_action"

    @pytest.mark.asyncio
    async def test_dispatch_tuple(self):
        """Test that _dispatch_result handles tuple return."""

        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return f"tuple:{request.activity}"

        api = MyAPI()
        result = await api._dispatch_result(("tuple_action",))
        assert result == "tuple:tuple_action"

    @pytest.mark.asyncio
    async def test_dispatch_tuple_with_data(self):
        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return f"tuple:{request.activity}:{request.data}"

        api = MyAPI()
        result = await api._dispatch_result(("action", {"key": "val"}))
        assert "tuple:action" in result

    @pytest.mark.asyncio
    async def test_dispatch_tuple_full(self):
        class MyAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return f"tuple:{request.activity}:{request.data}:{request.headers}"

        api = MyAPI()
        result = await api._dispatch_result(("action", {"k": "v"}, {"h": "1"}))
        assert "tuple:action" in result

    @pytest.mark.asyncio
    async def test_dispatch_direct(self):
        """Test that _dispatch_result passes through other values."""

        class MyAPI(APIClient[int]):
            async def invoke(self, request: ApiRequest) -> int:
                return 999  # should not be called

        api = MyAPI()
        result = await api._dispatch_result(42)
        assert result == 42


# ---------- Error Handling Tests ----------


class FailingAPI(APIClient[str]):
    """API that always fails."""

    async def invoke(self, request: ApiRequest) -> str:
        raise ConnectionError("API connection failed")


class TestAPIErrorHandling:
    @pytest.mark.asyncio
    async def test_api_invoke_error(self):
        api = FailingAPI()
        with pytest.raises(ConnectionError, match="API connection failed"):
            await api.call("test")

    @pytest.mark.asyncio
    async def test_api_dispatch_result_error(self):
        api = FailingAPI()
        with pytest.raises(ConnectionError):
            await api._dispatch_result(ApiRequest("test"))


# ---------- Generic Type Tests ----------


class TestGenericTypes:
    def test_generic_str(self):
        class StrAPI(APIClient[str]):
            async def invoke(self, request: ApiRequest) -> str:
                return "string"

        api = StrAPI()
        assert isinstance(api, APIClient)

    def test_generic_dict(self):
        class DictAPI(APIClient[Dict]):
            async def invoke(self, request: ApiRequest) -> Dict:
                return {}

        api = DictAPI()
        assert isinstance(api, APIClient)

    def test_generic_any(self):
        class AnyAPI(APIClient[Any]):
            async def invoke(self, request: ApiRequest) -> Any:
                return None

        api = AnyAPI()
        assert isinstance(api, APIClient)


# ---------- ApiRequest Serialization Tests ----------


class TestApiRequestSerialization:
    def test_request_as_dict(self):
        req = ApiRequest("test", {"a": 1}, {"h": "v"})
        d = {"activity": req.activity, "data": req.data, "headers": req.headers}
        assert d == {"activity": "test", "data": {"a": 1}, "headers": {"h": "v"}}

    def test_request_empty_data(self):
        req = ApiRequest("test")
        assert req.data == {}
        assert req.headers is None

    def test_request_nested_data(self):
        req = ApiRequest("test", {"nested": {"key": "value"}, "list": [1, 2, 3]})
        assert req.data["nested"]["key"] == "value"
        assert req.data["list"] == [1, 2, 3]
