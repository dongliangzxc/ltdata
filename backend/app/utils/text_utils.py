"""文本规范化工具：标题归一化，用于「同标题」类匹配（同标题批量处理、排除库标题兜底）。"""
import re
import unicodedata

_TITLE_PUNCT_RE = re.compile(
    r"[\s\-‐‑‒–—―_/\\|,，、.。·・•!！?？:：;；'‘’\"“”()（）\[\]【】{}<>《》&+@#＃$￥%％^*＊=~～`｀…]+"
)


def title_key(value: str | None) -> str:
    """把商品标题归一化为可比较的键：NFKC 全角转半角 + casefold + 去标点空白。"""
    normalized = unicodedata.normalize("NFKC", value or "").casefold().strip()
    return _TITLE_PUNCT_RE.sub("", normalized)
