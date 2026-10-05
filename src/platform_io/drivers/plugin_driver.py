"""提供 Platform IO 的插件消息网关驱动实现。"""

from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol

from src.platform_io.drivers.base import PlatformIODriver
from src.platform_io.types import DeliveryReceipt, DeliveryStatus, DriverDescriptor, DriverKind, RouteKey
from src.plugin_runtime.host.component_timeout import resolve_component_rpc_timeout_ms

if TYPE_CHECKING:
    from src.chat.message_receive.message import SessionMessage


class _GatewaySupervisorProtocol(Protocol):
    """消息网关驱动依赖的 Supervisor 最小协议。"""

    async def query_outbound_policy(
        self, plugin_id: str, component_name: str, args: Dict[str, Any], timeout_ms: int = 5000,
    ) -> Any:
        """独立策略查询通道。"""

    async def invoke_message_gateway(
        self,
        plugin_id: str,
        component_name: str,
        args: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 30000,
    ) -> Any:
        """调用插件声明的消息网关方法。"""


class PluginPlatformDriver(PlatformIODriver):
    """面向插件消息网关链路的 Platform IO 驱动。"""

    def __init__(
        self,
        driver_id: str,
        platform: str,
        supervisor: _GatewaySupervisorProtocol,
        component_name: str,
        *,
        supports_send: bool,
        account_id: Optional[str] = None,
        scope: Optional[str] = None,
        plugin_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化一个插件消息网关驱动。

        Args:
            driver_id: Broker 内的唯一驱动 ID。
            platform: 该消息网关负责的平台名称。
            supervisor: 持有该插件的 Supervisor。
            component_name: 出站时要调用的网关组件名称。
            supports_send: 当前驱动是否具备出站能力。
            account_id: 可选的账号 ID 或 self ID。
            scope: 可选的额外路由作用域。
            plugin_id: 拥有该实现的插件 ID。
            metadata: 可选的额外驱动元数据。
        """

        descriptor = DriverDescriptor(
            driver_id=driver_id,
            kind=DriverKind.PLUGIN,
            platform=platform,
            account_id=account_id,
            scope=scope,
            plugin_id=plugin_id,
            metadata=metadata or {},
        )
        super().__init__(descriptor)
        self._supervisor = supervisor
        self._component_name = component_name
        self._supports_send = supports_send
        self._timeout_ms = resolve_component_rpc_timeout_ms((metadata or {}).get("timeout_ms", 0))

    async def preflight_policy(self, message: "SessionMessage") -> Dict[str, Any]:
        """先协商再查询，不调用 send_message / invoke_message_gateway。"""
        from src.plugin_runtime.host.message_utils import PluginMessageUtils

        unavailable = {"allowed": False, "outcome": "preflight_unavailable", "reason": "策略预检不可用", "retryable": False}
        try:
            capabilities = await self._supervisor.query_outbound_policy(
                plugin_id=self.descriptor.plugin_id or "", component_name=self._component_name,
                args={"operation": "capabilities"}, timeout_ms=5000,
            )
            if capabilities.error or not isinstance(capabilities.payload, dict):
                return unavailable
            payload = capabilities.payload
            if payload.get("version") != 1 or type(payload.get("supported")) is not bool:
                return unavailable
            if payload["supported"] is False:
                return {"allowed": True, "outcome": "unsupported"}
            response = await self._supervisor.query_outbound_policy(
                plugin_id=self.descriptor.plugin_id or "", component_name=self._component_name,
                args={"operation": "check", "message": PluginMessageUtils._session_message_to_dict(message)},
                timeout_ms=5000,
            )
            if response.error or not isinstance(response.payload, dict):
                return unavailable
            payload = response.payload
            result = payload.get("result")
            if (payload.get("version") != 1 or payload.get("supported") is not True
                    or not isinstance(result, dict) or type(result.get("allowed")) is not bool):
                return unavailable
            outcome = result.get("outcome")
            if ((result["allowed"] and outcome != "allowed") or
                    (not result["allowed"] and outcome not in {"policy_dropped", "preflight_unavailable"})):
                return unavailable
            return {"allowed": result["allowed"], "outcome": outcome,
                    "reason": str(result.get("reason") or ""), "retryable": False}
        except Exception:
            return unavailable

    async def send_message(
        self,
        message: "SessionMessage",
        route_key: RouteKey,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DeliveryReceipt:
        """通过插件消息网关发送消息。

        Args:
            message: 要投递的内部会话消息。
            route_key: Broker 为本次投递选择的路由键。
            metadata: 可选的发送元数据。

        Returns:
            DeliveryReceipt: 规范化后的发送回执。
        """

        if not self._supports_send:
            return DeliveryReceipt(
                internal_message_id=message.message_id,
                route_key=route_key,
                status=DeliveryStatus.FAILED,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                error="当前消息网关仅支持接收，不支持发送",
            )

        from src.plugin_runtime.host.message_utils import PluginMessageUtils

        plugin_id = self.descriptor.plugin_id or ""
        if not plugin_id:
            return DeliveryReceipt(
                internal_message_id=message.message_id,
                route_key=route_key,
                status=DeliveryStatus.FAILED,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                error="插件消息网关驱动缺少 plugin_id",
            )

        try:
            message_dict = PluginMessageUtils._session_message_to_dict(message)
            response = await self._supervisor.invoke_message_gateway(
                plugin_id=plugin_id,
                component_name=self._component_name,
                args={
                    "message": message_dict,
                    "route": {
                        "platform": route_key.platform,
                        "account_id": route_key.account_id,
                        "scope": route_key.scope,
                    },
                    "metadata": metadata or {},
                },
                timeout_ms=self._timeout_ms,
            )
        except Exception as exc:
            return DeliveryReceipt(
                internal_message_id=message.message_id,
                route_key=route_key,
                status=DeliveryStatus.FAILED,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                error=str(exc),
                metadata={"delivery_unknown": True, "retryable": False},
            )

        return self._build_receipt(message.message_id, route_key, response)

    def _build_receipt(self, internal_message_id: str, route_key: RouteKey, response: Any) -> DeliveryReceipt:
        """将网关调用响应归一化为出站回执。

        Args:
            internal_message_id: 内部消息 ID。
            route_key: 本次投递的路由键。
            response: Supervisor 返回的 RPC 响应对象。

        Returns:
            DeliveryReceipt: 标准化后的出站回执。
        """

        if getattr(response, "error", None):
            error = response.error.get("message", "消息网关发送失败")
            return DeliveryReceipt(
                internal_message_id=internal_message_id,
                route_key=route_key,
                status=DeliveryStatus.FAILED,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                error=error,
                metadata={"delivery_unknown": True, "retryable": False},
            )

        payload = getattr(response, "payload", {})
        invoke_success = bool(payload.get("success", False)) if isinstance(payload, dict) else False
        if not invoke_success:
            return DeliveryReceipt(
                internal_message_id=internal_message_id,
                route_key=route_key,
                status=DeliveryStatus.FAILED,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                error=str(payload.get("result", "消息网关发送失败")) if isinstance(payload, dict) else "消息网关发送失败",
                metadata={"delivery_unknown": True, "retryable": False},
            )

        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict):
            if result.get("success") is False:
                # silent 仅表示不要回显错误，不能证明是策略拒绝。
                is_policy_drop = result.get("policy_drop") is True
                base_metadata = result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}
                receipt_metadata = dict(base_metadata)
                if is_policy_drop:
                    receipt_metadata["policy_drop"] = True
                    receipt_metadata["policy_reason"] = str(result.get("policy_reason") or result.get("error", ""))
                receipt_metadata["retryable"] = False
                if result.get("delivery_unknown") is True or (not is_policy_drop and "timeout" in str(result.get("error", "")).lower()):
                    receipt_metadata["delivery_unknown"] = True
                return DeliveryReceipt(
                    internal_message_id=internal_message_id,
                    route_key=route_key,
                    status=DeliveryStatus.DROPPED if is_policy_drop else DeliveryStatus.FAILED,
                    driver_id=self.driver_id,
                    driver_kind=self.descriptor.kind,
                    error=str(result.get("error", "消息网关发送失败")),
                    metadata=receipt_metadata,
                )
            external_message_id = str(result.get("external_message_id") or result.get("message_id") or "") or None
            # 正文回执不影响真实投递状态。损坏容器显式透传为无效正文，
            # 不能悄悄降级成旧驱动并把未发送的候选内容写进历史。
            raw_metadata = result.get("metadata", {})
            receipt_metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {"delivery_content": None}
            return DeliveryReceipt(
                internal_message_id=internal_message_id,
                route_key=route_key,
                status=DeliveryStatus.SENT,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                external_message_id=external_message_id,
                metadata=receipt_metadata,
            )

        if isinstance(result, str) and result.strip():
            return DeliveryReceipt(
                internal_message_id=internal_message_id,
                route_key=route_key,
                status=DeliveryStatus.SENT,
                driver_id=self.driver_id,
                driver_kind=self.descriptor.kind,
                external_message_id=result.strip(),
            )

        return DeliveryReceipt(
            internal_message_id=internal_message_id,
            route_key=route_key,
            status=DeliveryStatus.SENT,
            driver_id=self.driver_id,
            driver_kind=self.descriptor.kind,
        )
