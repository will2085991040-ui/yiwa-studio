"""样式预设：把风格 key 翻译成生图/生视频模型可用的 prompt 增强词与负面词。"""

STYLE_PRESETS: dict[str, dict] = {
    "anime": {
        "label": "二次元动漫",
        "prompt": ("masterpiece anime illustration, "
                    "cel shading, clean lineart, vivid anime key visual"),
        "negative": "photorealistic, 3d render, deformed",
    },
    "realistic": {
        "label": "真人写实",
        "prompt": ("photorealistic film still, ultra detailed, "
                    "natural lighting, subtle film grain"),
        "negative": "anime, illustration, drawn, oversaturated",
    },
    "dynamic_manga": {
        "label": "动态漫画",
        "prompt": ("dynamic manga dynamic ink outlines, halftone screentone, "
                    "high contrast action lines"),
        "negative": "photorealistic, 3d, flat",
    },
    "cinematic": {
        "label": "史诗电影感",
        "prompt": ("cinematic movie still, anamorphic, dramatic lighting, "
                    "rich color grade, shallow depth of field"),
        "negative": "flat lighting, illustration",
    },
    "cyberpunk": {
        "label": "赛博朋克",
        "prompt": "cyberpunk, holographic neon, futuristic, moody",
        "negative": "bright daylight, pastoral",
    },
    "shuimo": {
        "label": "水墨国风",
        "prompt": "Chinese ink painting, soft brush strokes, paper texture",
        "negative": "realistic, saturated, 3d",
    },
    "clay": {
        "label": "黏土定格",
        "prompt": "claymation, soft toy figures, cozy props, stop-motion look",
        "negative": "photo, realistic skin",
    },
    "gothic": {
        "label": "暗黑哥特",
        "prompt": "dark gothic, ornate, candlelight, deep shadows",
        "negative": "cute, chibi, bright",
    },
}

STYLE_LABELS = {k: v['label'] for k, v in STYLE_PRESETS.items()}


def style_names() -> list[str]:
    return list(STYLE_PRESETS.keys())


def style_label(key: str) -> str:
    return STYLE_LABELS.get((key or '').lower(), key or '')


def style_keyword(key: str) -> str:
    p = STYLE_PRESETS.get((key or '').lower())
    return (p or {}).get('prompt', '')


def negative_extra(key: str) -> str:
    p = STYLE_PRESETS.get((key or '').lower())
    return (p or {}).get('negative', '')


def decorate(prompt: str, style: str | None = None, negative: str = '') -> tuple[str, str]:
    """把风格并入 prompt 前部；负面词与风格负面合并。"""
    kw = style_keyword(style)
    if kw:
        prompt = (kw + ', ' + prompt) if prompt else kw
    ex = negative_extra(style)
    if ex and negative:
        negative = negative + ', ' + ex
    elif ex:
        negative = ex
    return prompt, negative


def style_catalog() -> list[dict]:
    return [{'id': k, 'label': v['label'], 'sample': v['prompt'][:60]} for k, v in STYLE_PRESETS.items()]
