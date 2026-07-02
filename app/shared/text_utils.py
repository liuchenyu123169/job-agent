"""中文友好的文本工具 — bigram 提取、相关性粗滤。

这些函数供 external_search（过滤层）和 verifier（验收层）共用，
目标是拦截完全无关的结果，不做排序或语义理解。
"""

import re


def char_bigrams(text: str) -> set[str]:
    """提取中文 bigram + 英文小写单词，用于粗粒度相关性检测。

    中文部分：对连续 CJK 字符序列做字符级 bigram。
    英文部分：单词做 unigram，小写。

    >>> char_bigrams("腾讯后端")
    {'腾讯', '讯后', '后端'}
    >>> char_bigrams("Go backend dev")
    {'go', 'backend', 'dev'}
    """
    result: set[str] = set()
    # CJK 字符序列 → bigram
    for seq in re.findall(r'[一-鿿]+', text):
        for i in range(len(seq) - 1):
            result.add(seq[i:i + 2])
    # 单个 CJK 字符也加入（处理单字词如"AI工程师"中的孤立字）
    for seq in re.findall(r'[一-鿿]+', text):
        if len(seq) == 1:
            result.add(seq)
    # 英文单词 → 小写 unigram
    result.update(w.lower() for w in re.findall(r'[a-zA-Z]{2,}', text))
    return result


def min_relevance_signal(
    query: str,
    title: str = "",
    snippet: str = "",
    threshold: float = 0.05,
) -> bool:
    """返回 True 表示 query 与 (title + snippet) 有最低相关性信号。

    使用字符 bigram Jaccard 相似度，threshold=0.05 意味着：
    query 有 20 个 bigram 时只需命中 1 个即可通过。
    这不是排序器，只拦截完全无关的结果。

    无法计算时（两端有一方无有效 bigram）→ 返回 True，不误杀。
    """
    q = char_bigrams(query)
    t = char_bigrams(title) | char_bigrams(snippet)
    if not q or not t:
        return True  # 无法计算时不误杀
    jaccard = len(q & t) / len(q | t)
    return jaccard >= threshold
