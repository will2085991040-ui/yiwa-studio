"""FastAPI 入口：装配日志、异常处理、路由。"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.actions import router as actions_router
from app.api.v1.assets import router as assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.context_api import router as context_router
from app.api.v1.credits import router as credits_router
from app.api.v1.director import router as director_router
from app.api.v1.if_export import router as if_export_router
from app.api.v1.materials import router as materials_router
from app.api.v1.media import router as media_router
from app.api.v1.minigame import router as minigame_router
from app.api.v1.novel_import import router as novel_import_router
from app.api.v1.orchestrate import router as orchestrate_router
from app.api.v1.play import router as play_router
from app.api.v1.portraits import router as portraits_router
from app.api.v1.projects import router as projects_router
from app.api.v1.prompts import router as prompts_router
from app.api.v1.relations import router as relations_router
from app.api.v1.runtime import router as runtime_router
from app.api.v1.scripts import router as scripts_router
from app.api.v1.settings import router as settings_router
from app.api.v1.skills import router as skills_router
from app.api.v1.storyboard import router as storyboard_router
from app.api.v1.storygraph import router as storygraph_router
from app.api.v1.workspace import router as workspace_router
from app.api.v1.world_play import router as world_play_router
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.services.auth import require_user
from app.services.auth import verify_token
from app.services import credits as credits_service

setup_logging()


def create_app() -> FastAPI:
    """装配一只 FastAPI 应用（桌面版复用同一路由，不重复实现）。"""
    app = FastAPI(title="AI Interactive Growth Agent", version="0.1.0-phase0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Phase 0：本地/容器内联调；Phase 3 收紧
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    @app.middleware("http")
    async def _bind_credit_user(request, call_next):
        # 从 Bearer token 解析当前用户并绑定到请求上下文：代理结算时为其记点数消费。
        auth = request.headers.get("authorization", "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        user_id = verify_token(token) if token else None
        if user_id:
            ctoken = credits_service.bind_user_context(str(user_id))
            try:
                return await call_next(request)
            finally:
                credits_service.reset_user_context(ctoken)
        return await call_next(request)

    # auth 路由保持公开（register/login）；其余全部项目/配置接口由 require_user 保护。
    # require_user 在 AUTH_REQUIRED=true（生产 EXE）时强制登录，开发/test 放行以保留离线用例。
    app.include_router(auth_router)
    app.include_router(projects_router, dependencies=[Depends(require_user)])
    app.include_router(prompts_router, dependencies=[Depends(require_user)])
    app.include_router(director_router, dependencies=[Depends(require_user)])
    app.include_router(novel_import_router, dependencies=[Depends(require_user)])
    app.include_router(orchestrate_router, dependencies=[Depends(require_user)])
    app.include_router(workspace_router, dependencies=[Depends(require_user)])
    app.include_router(runtime_router, dependencies=[Depends(require_user)])
    app.include_router(settings_router, dependencies=[Depends(require_user)])
    app.include_router(context_router, dependencies=[Depends(require_user)])
    app.include_router(actions_router, dependencies=[Depends(require_user)])
    app.include_router(skills_router, dependencies=[Depends(require_user)])
    app.include_router(branches_router, dependencies=[Depends(require_user)])
    app.include_router(materials_router, dependencies=[Depends(require_user)])
    app.include_router(media_router, dependencies=[Depends(require_user)])
    app.include_router(play_router, dependencies=[Depends(require_user)])
    app.include_router(storygraph_router, dependencies=[Depends(require_user)])
    app.include_router(scripts_router, dependencies=[Depends(require_user)])
    app.include_router(portraits_router, dependencies=[Depends(require_user)])
    app.include_router(storyboard_router, dependencies=[Depends(require_user)])
    app.include_router(minigame_router, dependencies=[Depends(require_user)])
    app.include_router(world_play_router, dependencies=[Depends(require_user)])
    app.include_router(if_export_router, dependencies=[Depends(require_user)])
    app.include_router(relations_router, dependencies=[Depends(require_user)])
    app.include_router(assets_router, dependencies=[Depends(require_user)])
    app.include_router(credits_router, dependencies=[Depends(require_user)])
    return app


app = create_app()
