"""应用配置：全部来自环境变量（.env 可选），禁止硬编码密钥。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # 是否强制登录（Step 21+）：AUTH_REQUIRED=true 时所有项目接口都需要 Bearer JWT。
    # 桌面 EXE 由 launcher 注入为 true（生产强制登录）；开发/test 默认 false 以保留既有离线用例。
    auth_required: bool = False

    # 本地开发默认 SQLite，生产用 PostgreSQL（docker-compose 注入）
    database_url: str = "sqlite:///./dev.db"

    # LLM（OpenAI 兼容层）：LLM_PROVIDER=mock 时完全离线
    llm_provider: str = "openai_compat"  # mock | openai_compat（接 tokenhub 网关默认已指向生成剧本模型）
    llm_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash-0731"    # 剧本生成模型（tokenhub 网关实际模型名）
    # 专用剧本生成模型：留空则复用 llm_model。接火山方舟等自定义端点时填 ep-xxxx 形态的模型名。
    llm_script_model: str = ""
    llm_temperature: float = 0.7
    llm_timeout_seconds: int = 180   # 单次 LLM 请求超时（秒）；剧情/分镜等长结构化输出易超 60s，放宽到 180s 避免“请求超时”
    llm_max_retries: int = 3
    llm_retry_backoff: float = 0.5
    llm_embedding_model: str = ""
    llm_disable_thinking: bool = False   # True: 结构化生成时向 DeepSeek/方舟推理模型发 thinking:disabled（更快更省）

    # 桌面数据目录（launcher 注入；空则回退 %APPDATA%/YIWA/data）
    yiwa_data_dir: str = ""

    # 生图（硅基流动 SiliconFlow：OpenAI 兼容 images 端点）
    image_provider: str = "mock"                    # mock | siliconflow
    image_base_url: str = "https://api.siliconflow.cn/v1"
    image_api_key: str = ""
    image_model: str = "black-forest-labs/FLUX.1-schnell"
    image_size: str = "1024x1024"

    # 生视频（即梦/火山方舟 Seedance 内容生成任务）
    video_provider: str = "mock"                    # mock | seedance | minimax(tokenhub) | metaso_minimax(秘塔/MiniMax)
    video_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    video_api_key: str = ""
    video_model: str = "minimax-video-h3"    # tokenhub 视频模型（需开通后付费计费）
    # 秘塔/MiniMax 视频查询端点模板（{task} 为占位）：提交成功也会 task_id，轮询按该路径查状态。
    video_query_path: str = "/api/minimax/v2/video_generation/{task}"
    video_poll_interval: float = 3.0
    video_max_polls: int = 120

    # YIWA 生成服务（对照 Funloom Token）：单 Token + 可配网关，替代直填各厂 key。
    # 网关契约（自研，OpenAI/HTTP 兼容）：Bearer {yiwa_token}
    #   POST /v1/chat/completions（文本）  POST /v1/images/generations（生图）
    #   POST /v1/videos/generations（提交） GET /v1/videos/generations/{id}（轮询）
    yiwa_token: str = ""                            # 形如 yiwa_xxxx 的单一凭据
    yiwa_gateway_url: str = ""                      # 例如 https://gateway.yiwa.example/api

    # 登录注册 JWT 签名密钥（Step 21）。生产务必通过环境变量 AUTH_SECRET 注入；
    # 为空时自动派生自 yiwa_token/主机名 salt（settings 启动后由 auth 模块计算）。
    auth_secret: str = ""

    # 管理员用户名（逗号分隔，可多个）：系统启动时把这些用户提升为 role=admin。
    # 为空时：若某用户名叫 admin 则提升它；若仍无任何 admin，首次启动时把第一个注册用户提升为 admin。
    admin_usernames: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
