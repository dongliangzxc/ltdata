"""URL解析工具：从商品链接中提取 (platform, item_id)"""
from urllib.parse import urlparse, parse_qs


def extract_item_id(url: str | None) -> tuple[str, str] | None:
    """
    从商品URL提取 (platform, item_id)。
    支持 JD / TMALL / TAOBAO / SUNING，其他平台返回 None。

    Examples:
        https://item.jd.com/100045223280.html  → ("jd", "100045223280")
        https://detail.tmall.com/item.htm?id=738271928  → ("tmall", "738271928")
        https://item.taobao.com/item.htm?id=655781234   → ("taobao", "655781234")
        https://product.suning.com/0070171620/11498580.html → ("suning", "11498580")
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        # JD: item.jd.com/{item_id}.html
        if "item.jd.com" in host:
            path = parsed.path.rstrip("/")
            filename = path.rsplit("/", 1)[-1]
            item_id = filename.replace(".html", "").strip()
            return ("jd", item_id) if item_id else None

        # TMALL: detail.tmall.com/item.htm?id={item_id}
        if "tmall.com" in host:
            qs = parse_qs(parsed.query)
            item_id_list = qs.get("id", [])
            return ("tmall", item_id_list[0]) if item_id_list else None

        # TAOBAO: item.taobao.com/item.htm?id={item_id}
        if "taobao.com" in host:
            qs = parse_qs(parsed.query)
            item_id_list = qs.get("id", [])
            return ("taobao", item_id_list[0]) if item_id_list else None

        # SUNING: product.suning.com/{shop_id}/{item_id}.html
        if "suning.com" in host:
            path = parsed.path.rstrip("/")
            filename = path.rsplit("/", 1)[-1]
            item_id = filename.replace(".html", "").strip()
            return ("suning", item_id) if item_id else None

    except Exception:
        pass

    return None
