"""统一业务异常与全局异常处理。"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 媒体生成统一错误：生图/生视频失败需透出可读信息，而非吞成 500。
from app.media.types import MediaError


class AppError(Exception):
    """业务异常：携带 HTTP 状态码与错误码。"""

    def __init__(self, message: str, *, code: str = "app_error", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code="not_found", status=404)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "请先登录"):
        super().__init__(message, code="unauthorized", status=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "没有权限执行此操作"):
        super().__init__(message, code="forbidden", status=403)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        import logging

        logging.getLogger("app").exception("unhandled error")
        # 把真实原因同时送回前端（本应用为本地桌面工具，便于用户自判），不再只提示“请查看日志”。
        # 只取异常类型 + 简短信息，避免拖入密钥；完整堆栈仍在日志里。
        detail = str(exc) or ""
        if len(detail) > 160:
            detail = detail[:160] + "…"
        message = f"服务器内部错误：{type(exc).__name__}" + (f" — {detail}" if detail else "")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal", "message": message}},
        )

    # 媒体生成（生图/生视频）失败应返回可读错误而非 500：把厂商/网络/任务失败
    # 的底层原因透出给用户（此前 MediaError 未注册处理器 → 走了通用 500「请查看日志」）。
    @app.exception_handler(MediaError)
    async def _media_error(request: Request, exc: MediaError):
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "media_error", "message": str(exc) or "媒体生成失败，请稍后重试"}},
        )
