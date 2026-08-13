"""Off-topic relevance gate + non-English description handling.

Fixtures are the real rows that motivated this: pirate-streaming and
proxy/geo-spoof lists riding GitHub trending onto an AI board, and Chinese
AI repos whose descriptions are Chinese-only or bilingual. The controls that
matter: the leaks drop, and NOTHING legit drops with them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hotin import board, engine
from hotin.sources import _readme_desc


def _repo(name, desc="", **signal):
    return {"name": name, "meta": {"description": desc}, "signal": signal}


# --- relevance gate ---------------------------------------------------------

def test_offtopic_leaks_drop():
    # awesome-zhuiju-free: binge-watch/torrent resource list
    assert engine.is_offtopic(_repo(
        "laoma2053/awesome-zhuiju-free",
        "免费无广告的追剧资源指南，收录在线影视、磁力BT、IPTV直播源、TVBox 配置地址")) is True
    # wloc: Apple location spoof for proxy clients
    assert engine.is_offtopic(_repo(
        "yu9191/wloc",
        "修改 Apple 网络定位（gs-loc）返回坐标 · 支持 Surge / Quantumult X / Loon / Stash")) is True
    # English-language piracy list drops too (language-agnostic)
    assert engine.is_offtopic(_repo("x/y", "Free IPTV and TVBox playlists, magnet links")) is True


def test_offtopic_keeps_legit_ai_repos():
    for name, desc in [
        ("moonshotai/kimi-k3", "Kimi-K3 Technical Report"),
        ("basketikun/infinite-canvas", "面向 AI 创作的开源无限画布工作台，集成 AI 生图、Agent 智能助手"),
        ("saladday/pi-from-scratch", "600 行 TypeScript 写成的超级迷你版 pi-agent"),
        ("zai-org/GLM-5.2", "GLM-5.2 supports deployment with vLLM and SGLang"),
    ]:
        assert engine.is_offtopic(_repo(name, desc)) is False, name


def test_ai_provenance_shields_even_on_term_match():
    # A repo that trips a term but carries an insider star is NOT dropped.
    assert engine.is_offtopic(
        _repo("a/b", "IPTV agent orchestration", smartmoney_starrers=2)) is False
    r = {"name": "a/b", "meta": {"description": "tvbox", "paper_backed": True}, "signal": {}}
    assert engine.is_offtopic(r) is False


def test_drop_offtopic_preserves_order_and_survivors():
    rows = [_repo("keep/one", "an LLM agent"),
            _repo("x/pirate", "追剧 IPTV TVBox 磁力"),
            _repo("keep/two", "diffusion model")]
    out = engine.drop_offtopic(rows)
    assert [r["name"] for r in out] == ["keep/one", "keep/two"]


# --- English preference / [zh] tag -----------------------------------------

def test_prefer_english_bilingual():
    assert board.prefer_english(
        "AI 短剧制作的 skill 集合 | Agent skills for AI short-drama production, screenplays"
    ) == "Agent skills for AI short-drama production, screenplays"
    assert board.prefer_english(
        "直连腾讯 iLink，登录用 OAuth。 Connects directly to Tencent iLink for chat."
    ) == "Connects directly to Tencent iLink for chat."


def test_prefer_english_leaves_monolingual_untouched():
    en = "An open 45M-parameter model for tool calling and device use"
    assert board.prefer_english(en) == en                      # pure English, fast path
    zh = "让 AI 写的中文读起来像一个具体的人在说话"
    assert board.prefer_english(zh) == zh                      # pure Chinese, unchanged
    # scattered Latin tokens inside a Chinese sentence are NOT a clause
    mixed = "600 行 TypeScript 写成的超级迷你版 pi-agent"
    assert board.prefer_english(mixed) == mixed


def test_cjk_dominant():
    assert board.is_cjk_dominant("面向 AI 创作的开源无限画布工作台") is True
    assert board.is_cjk_dominant("A regular English sentence") is False
    assert board.is_cjk_dominant("") is False


def test_clip_tags_chinese_only_and_not_english():
    assert board._clip("面向 AI 创作的开源无限画布工作台").startswith("[zh] ")
    out = board._clip("AI 短剧 | Agent skills for short-drama production, screenplays")
    assert out == "Agent skills for short-drama production, screenplays"  # English picked, no tag
    assert not board._clip("An open weights small model").startswith("[zh]")


# --- README nav-row rejection ----------------------------------------------

def test_rising_rows_route_through_clip():
    # regression: rising_rows once truncated raw, bypassing prefer_english/[zh]
    rows = board.rising_rows([{
        "canonical_repo": "a/b", "entity_id": "a/b", "url": "https://x",
        "meta": {"description": "中文简介 | An English rising-repo description here"}}])
    assert rows[0]["meta"] == "An English rising-repo description here"
    zh = board.rising_rows([{
        "canonical_repo": "c/d", "entity_id": "c/d", "url": "https://x",
        "meta": {"description": "面向 AI 创作的开源无限画布工作台"}}])
    assert zh[0]["meta"].startswith("[zh] ")


def test_is_prose_rejects_nav_row():
    assert _readme_desc._is_prose("English · 两种创作路径 · 开始使用 · 作品档案") is False
    assert _readme_desc._is_prose("Home | Docs | Examples | API") is False
    # a real sentence that merely contains a pipe stays prose
    assert _readme_desc._is_prose(
        "This tool converts Word and PowerPoint files into clean markdown output") is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
