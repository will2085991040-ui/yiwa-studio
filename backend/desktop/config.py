"""桌面版配置（Step 21）：首次启动生成 JSON 配置，集中管理路径 / LLM / API-Key。

纯标准库实现，不导入 `app`，保证在 `app` 包（会立即建立 DB 引擎）之前可用。
密钥不硬编码：llm_api_key 默认空，用户可在首次启动后填入 data_dir/config.json。
"""
import json
import os
from dataclasses import asdict, dataclass, field

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _default_data_dir() -> str:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(base, "YIWA", "data")


@dataclass
class DesktopConfig:
    data_dir: str = field(default_factory=_default_data_dir)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    open_browser: bool = True
    llm_provider: str = "openai_compat"     # mock | openai_compat（接腾讯 tokenhub 混元已内置默认端点）
    llm_base_url: str = "https://tokenhub.tencentmaas.com/v1"   # 网关端点（非用户网址），密钥仅露在 config.json
    llm_api_key: str = ""                     # 用户自行填写（config.json），不硬编码不进二进制
    llm_model: str = "deepseek-v4-flash-0731" # 剧本生成模型（tokenhub 网关实际模型名）
    llm_script_model: str = ""        # 剧本专用模型（缺省复用 llm_model），如火山方舟 ep-xxxx
    llm_disable_thinking: bool = False     # True: 结构化生成关闭推理模型的 thinking（更快更省）
    llm_timeout_seconds: int = 180         # 单次 LLM 请求超时（秒）；长剧情/分镜输出放宽防“请求超时”
    image_provider: str = "mock"            # mock | siliconflow
    image_base_url: str = "https://api.siliconflow.cn/v1"
    image_api_key: str = ""
    image_model: str = "black-forest-labs/FLUX.1-schnell"
    image_size: str = "1024x1024"
    video_provider: str = "mock"            # mock | minimax（tokenhub 网关，默认 mock 免计费）
    video_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    video_api_key: str = ""
    video_model: str = "minimax-video-h3"
    yiwa_token: str = ""                    # 单一 YIWA 生成凭据（yiwa_ 前缀）
    yiwa_gateway_url: str = ""              # YIWA 生成服务网关（Bearer 鉴权）
    web_root: str = ""                      # 前端静态产物目录；空则用内置启动页

    @property
    def database_url(self) -> str:
        return "sqlite:///" + os.path.join(self.data_dir, "yiwa.db").replace(os.sep, "/")

    @property
    def project_dir(self) -> str:
        return os.path.join(self.data_dir, "projects")

    @property
    def config_file(self) -> str:
        return os.path.join(self.data_dir, "config.json")

    def ensure_dirs(self) -> None:
        os.makedirs(self.project_dir, exist_ok=True)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DesktopConfig":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | None = None) -> DesktopConfig:
    cfg = DesktopConfig()
    file = path or cfg.config_file
    if file and os.path.exists(file):
        with open(file, encoding="utf-8") as fh:
            cfg = DesktopConfig.from_dict(json.load(fh))
    return cfg


def save_config(cfg: DesktopConfig, path: str | None = None) -> str:
    file = path or cfg.config_file
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, ensure_ascii=False, indent=2)
    return file