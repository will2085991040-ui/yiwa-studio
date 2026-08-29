"""CharacterPortrait（增量：Funloom 蒸馏 · Phase 2）——角色立绘 + 8 段外貌模板 + 差分。

吸收 Funloom 的「立绘 8 段模板 + 差分 + 基础立绘备份」模型：
- appearance 8 段：基本信息 / 面部特征 / 发型妆容 / 服饰装备 / 道具配饰 / 神态气质 / 姿态构图 / 光影渲染
- 基础立绘规则（全身立绘、稳定一致、可复用为视频资产）
- 差分 variants：差分类别 + 取值 + 提示词，promote 到基础立绘时自动保留「原基础立绘备份」
仅数据 + 纯函数（无 DB/LLM 依赖），服务层与 API 直接复用。
"""
from pydantic import BaseModel, Field, model_validator

# ---- 8 段外貌模板（key, 中文标签, 填写提示）----
APPEARANCE_SECTIONS: list[tuple[str, str, str]] = [
    ("basic", "基本信息", "性别、年龄段、种族/身份、题材定位和目标视觉风格。"),
    ("face", "面部特征", "脸型、肤色、眼睛、瞳色、五官特点和表情基调。"),
    ("hair", "发型妆容", "发色、发型、发饰、妆容或其他头部识别点。"),
    ("clothing", "服饰装备", "衣服款式、颜色、材质、时代感、职业感和层次。"),
    ("props", "道具配饰", "武器、包、饰品、标志物等会影响角色识别的元素。"),
    ("demeanor", "神态气质", "情绪、眼神、气场、性格外显，不写大段剧情。"),
    ("pose", "姿态构图", "站姿、正视/侧身、全身/半身、双足是否完整。"),
    ("lighting", "光影渲染", "光照、材质、清晰度、渲染风格和一致性要求。"),
]

STYLES = ["3D国风高清渲染风格", "皮影戏插画风格", "写实电影感", "二次元立绘"]
ASPECT_RATIOS = ["9:16", "16:9", "1:1"]

BASE_RULE = (
    "白色或干净透明感背景，水平正视，全身立绘，完整包含双足。"
    "保持脸型、体型、服装、标志道具与整体风格稳定一致，适合后续视频资产复用。"
)
VARIANT_RULE = "保持同一角色身份、脸型、体型比例、画风与全身立绘构图，只改变当前差分要求的内容。"


class PortraitVariant(BaseModel):
    """一个角色差分（表情/服装/饰品…），可提升为基础立绘。"""

    variant_id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=120, description="显示名（未命名差分等）")
    category: str | None = Field(default=None, max_length=80, description="差分类别，如 expression/outfit")
    value: str = Field(default="", max_length=120, description="类别取值，如 高兴/正装")
    description: str = Field(default="", max_length=600, description="差分提示词")
    style: str = Field(default="", max_length=40)
    aspect: str = Field(default="9:16", max_length=10)
    image: dict | None = Field(default=None, description="{source, data/material_id/storage_path/url} | null=未生成")
    status: str = Field(default="saved", max_length=20)  # saved | generating
    source: str = Field(default="seed", max_length=20)  # seed | upload | generated
    created_at: str = Field(default="", max_length=40)


class CharacterPortrait(BaseModel):
    """一个角色的立绘档案：8 段外貌 + 基础立绘 + 差分列表。"""

    character_id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=120)
    appearance: dict[str, str] = Field(default_factory=dict, description="8 段外貌 {basic,face,...: 文本}")
    style: str = Field(default="3D国风高清渲染风格", max_length=40)
    aspect: str = Field(default="9:16", max_length=10)
    base_variant_id: str | None = Field(default=None, max_length=80)
    variants: list[PortraitVariant] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_unique(self) -> "CharacterPortrait":
        ids = [v.variant_id for v in self.variants]
        if len(ids) != len(set(ids)):
            raise ValueError("variants 的 variant_id 不能重复")
        return self


def portrait_template() -> dict:
    """返回前端需要的立绘模板元信息（8 段 + 风格 + 比例 + 规则）。"""
    return {
        "sections": [{"key": k, "label": label, "hint": h} for k, label, h in APPEARANCE_SECTIONS],
        "styles": STYLES,
        "aspect_ratios": ASPECT_RATIOS,
        "base_rule": BASE_RULE,
        "variant_rule": VARIANT_RULE,
    }


def _appearance_lines(appearance: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key, label, _ in APPEARANCE_SECTIONS:
        text = (appearance.get(key) or "").strip()
        if text:
            lines.append(f"【{label}】{text}")
    return lines


def compose_base_prompt(portrait: CharacterPortrait) -> str:
    """合成基础立绘提示词：外貌分段 + 基础规则。"""
    lines = _appearance_lines(portrait.appearance)
    head = "外貌/立绘描述：" if lines else ""
    body = "\n".join(lines)
    style = portrait.style.strip()
    blocks = [p for p in (head + body if head else body, style, BASE_RULE) if p]
    return "\n".join(blocks)


def compose_variant_prompt(portrait: CharacterPortrait, variant: PortraitVariant) -> str:
    """合成差分提示词：基础外貌 + 差分类别/取值/提示词 + 一致性规则。"""
    blocks: list[str] = []
    base = compose_base_prompt(portrait)
    if base:
        blocks.append(base)
    if variant.category:
        blocks.append(f"差分类别：{variant.category}")
    if variant.value or variant.name:
        blocks.append(f"差分名称：{variant.value or variant.name}")
    desc = variant.description.strip()
    if desc:
        blocks.append(f"差分提示词：{desc}")
    blocks.append(VARIANT_RULE)
    return "\n".join(b for b in blocks if b)


def _unique_backup_name(variants: list[PortraitVariant]) -> str:
    label = "原基础立绘备份"
    names = {v.name for v in variants}
    if label not in names:
        return label
    i = 2
    while f"{label} {i}" in names:
        i += 1
    return f"{label} {i}"


def promote_variant(portrait: CharacterPortrait, variant_id: str) -> CharacterPortrait:
    """把某个差分提升为基础立绘；若旧基础立绘有图，自动保留「原基础立绘备份」。"""
    target = next((v for v in portrait.variants if v.variant_id == variant_id), None)
    if target is None:
        raise ValueError(f"差分 {variant_id} 不存在")

    old_base = (
        next((v for v in portrait.variants if v.variant_id == portrait.base_variant_id), None)
        if portrait.base_variant_id
        else None
    )

    variants = list(portrait.variants)
    if old_base is not None and old_base.image is not None and old_base.variant_id != variant_id:
        variants.append(
            PortraitVariant(
                variant_id=f"variant-backup-{variant_id}",
                name=_unique_backup_name(variants),
                category=None,
                value="",
                description="切换基础立绘时自动保留的上一张基础立绘",
                style=old_base.style,
                aspect=old_base.aspect,
                image=old_base.image,
                status="saved",
                source="seed",
                created_at=old_base.created_at,
            )
        )
    return portrait.model_copy(update={"base_variant_id": variant_id, "variants": variants})