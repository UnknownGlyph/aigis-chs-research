"""
Build Chinese-capable Aqualead ALFT bitmap fonts (MainFont.aft & MainFontFix.aft)
with exact original file sizes so Aigis.exe accepts them without any binary modification.

Strategy:
  1. Collect EVERY codepoint the client can actually put on screen:
       - all string pools of the post-patch tables (recursively through ALL4 -> ALAR v3 -> ALTB,
         including the 800+ nested event / paev03 archives),
       - UTF-8 literals hard-coded inside Aigis.exe (兵舎 / 神殿 / 選択 / 執務室 ...),
       - the curated MUST_KEEP_UI_CHARS list for text pushed by the server at runtime
         (present-box titles such as 「不具合のお詫び」「10/29緊急メンテナンス対応の補填」,
          mission rewards such as 「統帥の塔 第10階層 階層スコア」).
  2. Allocate the fixed glyph budget by MEASURED in-game usage frequency instead of blindly
     evicting "Japanese looking" slots, so a glyph that the UI actually draws can never be
     traded away for a Chinese character that is never displayed.
  3. Render only the glyphs that are genuinely missing; every codepoint that already exists in
     the original font keeps its original (style-matched) bitmap.
  4. Fill the exact original byte size (1,727,372 B / 1,618,424 B) with trailing zeros.

NOTE: the ALFT bitmap atlas is size-locked by Aigis.exe's cache check, so the glyph budget is
~4,280 cells per font. `build_chinese_alft` therefore reports `dropped_low_priority` explicitly
instead of silently producing red "missing glyph" boxes.
"""

import os
import re
import unicodedata
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple
from PIL import Image, ImageDraw, ImageFont

import aigis_formats as af

DEFAULT_TTF_CANDIDATES = [
    r"C:\Windows\Fonts\STZHONGS.TTF",   # 华文中宋 — matches Aigis's native bold Mincho/Serif style!
    r"C:\Windows\Fonts\STSONG.TTF",     # 华文宋体
    r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑 Bold (fallback)
    r"C:\Windows\Fonts\simhei.ttf",     # 黑体 (fallback)
]


def find_chinese_ttf(custom_path: Optional[str] = None) -> str:
    if custom_path and os.path.exists(custom_path):
        return custom_path
    for p in DEFAULT_TTF_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("No Simplified Chinese TTF/TTC font found in C:\\Windows\\Fonts")


HIGH_FREQ_SC_PRIORITY = (
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严"
    "龙飞剑魔神圣枪盾弓箭杖铠护卫骑士师法巫医贼忍武侍姬王女男灵妖兽鬼恶暗光炎冰雷风土水木金铁铜银黑蓝紫红白黄绿灰粉"
    "击杀伤防抗命血技被动觉醒晋升编队成员出撤退补给回复消耗费用上限等级经验突破强化继承素材合成仓库兵舍礼物箱兑换券结晶碎片金币"
    "任务关卡剧情主线每日紧急复刻大讨伐魔神降临神兽英杰统帅恶灵斗技场挑战演习指南交流好感信赖称号设置选项帮助公告日志登录签到"
    "确认取消返回继续开始结束跳过隐藏关闭开启切换选择搜索筛选排序锁定解锁查看详情预览渲染测试"
)


def get_gb2312_level1_codepoints() -> List[int]:
    """Return high-frequency Simplified Chinese chars first, then remaining GB2312 Level-1."""
    seen: Set[int] = set()
    cps: List[int] = []
    for ch in HIGH_FREQ_SC_PRIORITY:
        cp = ord(ch)
        if cp not in seen:
            seen.add(cp)
            cps.append(cp)
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            if hi == 0xD7 and lo >= 0xFA:
                continue
            try:
                ch = bytes([hi, lo]).decode("gb2312")
                cp = ord(ch)
                if cp not in seen:
                    seen.add(cp)
                    cps.append(cp)
            except UnicodeDecodeError:
                pass
    return cps


def render_glyph_28x28(ch: str, ttf_path: str, font_px: int = 24, y_offset: int = 0, supersample: int = 4) -> Tuple[int, bytes]:
    """
    Render a single CJK/punctuation glyph into Aigis 28x28 4-bit (0..15) bitmap format.
    Native Aigis MainFont.aft CJK metrics:
      - cell = 28x28
      - advance width = 24
      - ink box = x[0..23], y[0..23] (y[24..27] reserved for Latin descenders)
    """
    S = supersample
    cell = 28 * S
    box = 24 * S  # active ink area 24x24 inside 28x28

    # Cache loaded PIL fonts by (path, size)
    cache_key = (ttf_path, font_px * S)
    pil_font = _FONT_CACHE.get(cache_key)
    if pil_font is None:
        pil_font = ImageFont.truetype(ttf_path, font_px * S)
        _FONT_CACHE[cache_key] = pil_font

    # Mild 1px stroke at 4x supersample (= +0.25px) keeps Songti/Mincho horizontal hairlines
    # crisp and matched in visual weight to Aigis's native bold Mincho glyphs.
    sw = 1 if ("zhong" in ttf_path.lower() or "song" in ttf_path.lower() or "sun" in ttf_path.lower()) else 0

    # Render onto oversized canvas, measure exact ink bbox, and place consistently
    canvas = Image.new("L", (cell * 2, cell * 2), 0)
    draw = ImageDraw.Draw(canvas)
    ox, oy = cell // 2, cell // 2
    draw.text((ox, oy), ch, fill=255, font=pil_font, stroke_width=sw, stroke_fill=255)

    # Measure using a reference full-height CJK glyph ('国') baseline so punctuation
    # like '，', '。', '一' keeps its proper vertical position instead of getting vertically centered!
    ref_key = (ttf_path, font_px * S, sw, "ref_bbox")
    ref_bbox = _REF_CACHE.get(ref_key)
    if ref_bbox is None:
        ref_canvas = Image.new("L", (cell * 2, cell * 2), 0)
        ImageDraw.Draw(ref_canvas).text((ox, oy), "国", fill=255, font=pil_font, stroke_width=sw, stroke_fill=255)
        ref_bbox = ref_canvas.getbbox()
        _REF_CACHE[ref_key] = ref_bbox

    # Compute shift that maps '国' bbox center onto (box/2, box/2 + y_offset*S)
    rx0, ry0, rx1, ry1 = ref_bbox
    ref_cx = (rx0 + rx1) / 2.0
    ref_cy = (ry0 + ry1) / 2.0
    target_cx = box / 2.0
    target_cy = box / 2.0 + y_offset * S

    # Crop 28*S x 28*S window around shifted origin
    crop_x0 = int(round(ref_cx - target_cx))
    crop_y0 = int(round(ref_cy - target_cy))

    # Clamp horizontally only if this specific glyph overflows [0..24*S]
    g_bbox = canvas.getbbox()
    if g_bbox is not None:
        gx0, gy0, gx1, gy1 = g_bbox
        # If glyph ink extends past x=24*S or < 0, nudge minimally inside [0..24*S]
        if gx0 - crop_x0 < 0:
            crop_x0 = gx0
        elif gx1 - crop_x0 > box:
            crop_x0 = max(0, gx1 - box)
        if gy0 - crop_y0 < 0:
            crop_y0 = gy0
        elif gy1 - crop_y0 > box:
            crop_y0 = max(0, gy1 - box)

    cropped = canvas.crop((crop_x0, crop_y0, crop_x0 + cell, crop_y0 + cell))
    small = cropped.resize((28, 28), Image.Resampling.LANCZOS)

    # Quantize 0..255 -> 0..15 with mild contrast boost matching Aigis's crisp bitmap font
    px = list(small.getdata())
    buf = bytes(min(15, (v * 15 + 127) // 255) for v in px)

    # Fullwidth CJK/punctuation advance width is 24 (matches native Aigis MainFont.aft)
    adv = 24
    return adv, buf


_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
_REF_CACHE: Dict[Tuple[str, int, str], Tuple[int, int, int, int]] = {}


# ---------------------------------------------------------------------------
# Codepoint inventory: everything the client can actually draw
# ---------------------------------------------------------------------------

# Characters that only ever arrive from the SERVER (present-box titles, maintenance
# compensation mail, floor-score rewards) and therefore can never be found by scanning
# the local tables. Each entry below was observed as a red "missing glyph" box in-game:
#   不具合のお詫び / 10/29緊急メンテナンス対応の補填 / 統帥の塔 第10階層 階層スコア
#   第1兵舎 / ★4以下ユニット預かり所 / 一括選択・選択解除 / 任務報酬 / 記念キャンペーン
MUST_KEEP_UI_CHARS = "詫層緊舎預択報記階"

_JIS_L1: Optional[Set[int]] = None


def jis_level1_codepoints() -> Set[int]:
    """JIS X 0208 Level-1 kanji (rows 16-47) — the everyday Japanese kanji set."""
    global _JIS_L1
    if _JIS_L1 is None:
        cps: Set[int] = set()
        for b1 in range(0x88, 0x99):
            for b2 in range(0x40, 0xFD):
                try:
                    cps.add(ord(bytes([b1, b2]).decode("cp932")))
                except UnicodeDecodeError:
                    pass
        _JIS_L1 = cps
    return _JIS_L1


def _is_displayable_jp(cp: int) -> bool:
    """True for kana / CJK punctuation / fullwidth forms / JIS Level-1 kanji."""
    if 0x3000 <= cp <= 0x30FF or 0xFF01 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6:
        return True
    return cp in jis_level1_codepoints()


def scan_exe_ui_literals(exe_path: str, min_run: int = 2) -> Set[int]:
    """
    Extract CJK text hard-coded as UTF-8 literals inside Aigis.exe.

    The exe draws a number of labels that never appear in any .atb table
    (兵舎 / 神殿 / 執務室 / 選択 / 一括選択 / ★4以下ユニット預かり所 ...).  A naive
    "decode the whole PE as UTF-8 and keep every CJK char" pass produces thousands of
    false positives from binary noise, so a run is only accepted when every character
    is a plausible Japanese character (kana / punctuation / JIS Level-1 kanji).
    """
    if not exe_path or not os.path.exists(exe_path):
        return set()
    raw = open(exe_path, "rb").read()
    text = raw.decode("utf-8", errors="ignore")

    found: Set[int] = set()
    run: List[int] = []
    for ch in text:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF or 0x3000 <= cp <= 0x303F or 0xFF01 <= cp <= 0xFF60:
            run.append(cp)
        else:
            if len(run) >= min_run and all(_is_displayable_jp(cp) for cp in run):
                found.update(run)
            run = []
    if len(run) >= min_run and all(_is_displayable_jp(cp) for cp in run):
        found.update(run)
    return found


def _walk_payload(
    payload: bytes,
    cps: Set[int],
    weights: Counter,
    stats: Dict[str, int],
    depth: int = 0,
    examples: Optional[Dict[int, List[str]]] = None,
) -> None:
    """Recursively decode ALL4 -> ALAR v3 -> ALTB and accumulate every displayed codepoint."""
    if depth > 6 or len(payload) < 8:
        return
    head = payload[:4]
    if head == b"ALL4":
        stats["all4"] += 1
        try:
            _walk_payload(af.decompress_all4(payload)[2], cps, weights, stats, depth + 1, examples)
        except Exception:
            stats["fail"] += 1
    elif head == b"ALTB":
        try:
            tbl = af.parse_altb(payload)
            txt = tbl.string_pool.decode("utf-8", errors="ignore")
            stats["altb"] += 1
        except Exception:
            stats["fail"] += 1
            return
        for ch in txt:
            cp = ord(ch)
            if 0x21 <= cp <= 0xFFFF:
                cps.add(cp)
                weights[cp] += 1
        if examples is not None:
            for ch in set(txt):
                cp = ord(ch)
                if cp < 0x21 or len(examples.get(cp, ())) >= 2:
                    continue
                i = txt.find(ch)
                snippet = txt[max(0, i - 12) : i + 13].replace("\n", " ")
                snippet = "".join(c for c in snippet if c >= " " or c == " ")
                examples.setdefault(cp, []).append(snippet)
    elif head == b"ALAR":
        stats["alar"] += 1
        try:
            entries = af.parse_alar_v3(payload)
        except Exception:
            stats["fail"] += 1
            return
        for e in entries:
            _walk_payload(e.data, cps, weights, stats, depth + 1, examples)


def collect_displayed_text(
    game_dir: str,
    patch_out_dir: Optional[str] = None,
    examples: Optional[Dict[int, List[str]]] = None,
) -> Tuple[Set[int], Counter]:
    """
    Collect (codepoints, occurrence-weights) for EVERY character the patched client can display.

    Reads the post-patch tables in preference to the originals (so Japanese kanji that the
    Chinese translation made unreachable stop consuming glyph slots) and recurses through the
    nested .aar archives — the previous implementation only looked at top-level ALTB files,
    which silently dropped every event / paev03 story table and caused the red boxes.
    """
    cache_dir = os.path.join(game_dir, ".cache")
    patch_cache = os.path.join(patch_out_dir, ".cache") if patch_out_dir else None

    cps: Set[int] = set()
    weights: Counter = Counter()
    stats = {"all4": 0, "altb": 0, "alar": 0, "fail": 0, "files": 0}

    if os.path.isdir(cache_dir):
        for fn in sorted(os.listdir(cache_dir)):
            if fn.endswith(".md5") or fn.endswith(".tmp"):
                continue
            src = os.path.join(cache_dir, fn)
            if not os.path.isfile(src):
                continue
            if patch_cache and os.path.exists(os.path.join(patch_cache, fn)):
                src = os.path.join(patch_cache, fn)
            try:
                raw = open(src, "rb").read()
            except OSError:
                continue
            stats["files"] += 1
            _walk_payload(raw, cps, weights, stats, examples=examples)

    # UTF-8 literals hard-coded in the executable (pure client-side UI labels)
    for exe_name in ("Aigis.exe", "aigis_exe.exe"):
        exe_path = os.path.join(game_dir, exe_name)
        if os.path.exists(exe_path):
            exe_cps = scan_exe_ui_literals(exe_path)
            cps |= exe_cps
            for cp in exe_cps:
                weights[cp] += 1
            break

    # Base inventory that must always stay renderable
    base: Set[int] = set(range(0x21, 0x7F))
    base |= set(range(0x3000, 0x30FF))
    base |= set(range(0xFF01, 0xFF60))
    cps |= base
    for cp in base:
        weights[cp] += 1

    collect_displayed_text.last_stats = stats  # type: ignore[attr-defined]
    return cps, weights


def collect_used_game_codepoints(game_dir: str, patch_out_dir: Optional[str] = None) -> Set[int]:
    """Backwards-compatible wrapper returning just the codepoint set."""
    return collect_displayed_text(game_dir, patch_out_dir=patch_out_dir)[0]


def collect_display_priority_codepoints(game_dir: str, patch_out_dir: Optional[str] = None) -> Set[int]:
    """
    Codepoints that live in the WHITELISTED display columns of catalog.py.

    A raw string-pool scan cannot tell a displayed sentence from an internal ID or a dead string
    (`item_007000藍翼の大天狗ナゴミtrade_item`), so pool-only characters would compete with real
    UI text for the fixed glyph budget and could be kept while a visible character got evicted.
    These codepoints are ranked above pool-only characters so that everything the player can
    actually read always has a glyph.
    """
    try:
        from catalog import ALAR_ARCHIVES, TRANSLATABLE_TABLES
    except Exception:
        return set()

    cache_dir = os.path.join(game_dir, ".cache")
    patch_cache = os.path.join(patch_out_dir, ".cache") if patch_out_dir else None
    cps: Set[int] = set()

    def scan_tbl(tbl: "af.AltbTable", columns: Iterable[str]) -> None:
        if not (tbl.form & 0x04):
            return
        for row in range(tbl.count):
            strs = tbl.get_row_strings(row)
            for col in columns:
                val = strs.get(col) or ""
                for ch in val:
                    cp = ord(ch)
                    if 0x21 <= cp <= 0xFFFF:
                        cps.add(cp)

    def load(sha: str) -> Optional[bytes]:
        src = os.path.join(cache_dir, sha)
        if patch_cache and os.path.exists(os.path.join(patch_cache, sha)):
            src = os.path.join(patch_cache, sha)
        if not os.path.exists(src):
            return None
        raw = open(src, "rb").read()
        return af.decompress_all4(raw)[2] if af.is_all4(raw) else raw

    for spec in TRANSLATABLE_TABLES:
        payload = load(spec.sha256)
        if payload and payload[:4] == b"ALTB":
            try:
                scan_tbl(af.parse_altb(payload), spec.columns)
            except Exception:
                pass

    for aspec in ALAR_ARCHIVES:
        payload = load(aspec.sha256)
        if not payload or payload[:4] != b"ALAR":
            continue
        try:
            entries = af.parse_alar_v3(payload)
        except Exception:
            continue
        for e in entries:
            subs = af.parse_alar_v3(e.data) if af.is_alar_v3(e.data) else [e]
            for se in subs:
                data = se.data
                if data[:4] == b"ALL4":
                    try:
                        data = af.decompress_all4(data)[2]
                    except Exception:
                        continue
                if data[:4] != b"ALTB":
                    continue
                try:
                    scan_tbl(af.parse_altb(data), aspec.columns)
                except Exception:
                    pass
    return cps


_SCRIPTY = re.compile(r"[()\[\]{}=,;\"'<>|%\\]")
_KEYLIKE = re.compile(r"_|[A-Za-z]{3,}")
_ASCII_ONLY = re.compile(r"^[\x20-\x7e]*$")


def collect_table_text_codepoints(game_dir: str, patch_out_dir: Optional[str] = None) -> Set[int]:
    """
    Characters that appear in the *text* columns of every local ALTB table, translated or not.

    Rationale: catalog.py lists the tables we translate, but the client also loads numbered
    variants (`QuestNameText110002.atb`, `MessageText110002.atb`, ...) and small config tables
    that ship with kanji-only Japanese (`人間 / 獣人 / 重鎧 / 重騎`).  Those strings are drawn on
    screen, so every character in them needs a glyph — otherwise the client paints its red
    missing-glyph box.  Values that look like script expressions (`IsEnemyElementAny("...")`),
    numeric configs (`属性=物理,魔法`) or resource keys (`item_007000…trade_item`) are skipped so
    they do not steal budget from real text.
    """
    cache_dir = os.path.join(game_dir, ".cache")
    patch_cache = os.path.join(patch_out_dir, ".cache") if patch_out_dir else None
    cps: Set[int] = set()
    if not os.path.isdir(cache_dir) and not patch_cache:
        return cps

    def feed(val: str) -> None:
        if not val or _ASCII_ONLY.match(val) or _SCRIPTY.search(val) or _KEYLIKE.search(val):
            return
        for ch in val:
            cp = ord(ch)
            if 0x21 <= cp <= 0xFFFF:
                cps.add(cp)

    seen: Set[str] = set()
    for src_dir in [d for d in (cache_dir, patch_cache) if d and os.path.isdir(d)]:
        for fn in os.listdir(src_dir):
            if fn.endswith(".md5"):
                continue
            path = os.path.join(src_dir, fn)
            try:
                if os.path.getsize(path) > 4 * 1024 * 1024:
                    continue
                raw = open(path, "rb").read()
            except OSError:
                continue
            if raw[:4] == b"ALAR":
                continue
            payload = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
            if payload[:4] != b"ALTB" or payload in seen:
                continue
            seen.add(payload)
            try:
                tbl = af.parse_altb(payload)
            except Exception:
                continue
            if not (tbl.form & 0x04):
                continue
            try:
                fields = [f.name_en for f in tbl.string_fields()]
            except Exception:
                continue
            for row in range(tbl.count):
                vals = tbl.get_row_strings(row)
                for col in fields:
                    feed(vals.get(col) or "")
    return cps


# ---------------------------------------------------------------------------
# Glyph budget allocation
# ---------------------------------------------------------------------------

# Codepoints that must ALWAYS stay renderable, regardless of measured usage:
# ASCII, kana, CJK punctuation, fullwidth forms (and halfwidth kana range tail).
# Unassigned code points are filtered out — they would burn atlas cells for nothing.
def _assigned(cps: Iterable[int]) -> Set[int]:
    return {cp for cp in cps if unicodedata.category(chr(cp)) != "Cn"}


_BASE_ALWAYS = _assigned(
    set(range(0x21, 0x7F))
    | set(range(0x3000, 0x30FF))
    | set(range(0xFF01, 0xFF60))
    | set(range(0xFFE0, 0xFFE6))
)


def _blank_glyph(font: af.AlftFont) -> Tuple[int, bytes]:
    return (24, bytes(font.gw * font.gh))


def _fit_capacity(font: af.AlftFont, target_size: int, ranked_cps: List[int]) -> int:
    """
    Largest prefix length of `ranked_cps` whose serialized ALFT still fits `target_size` bytes.

    Aigis.exe compares the cached font size against the server manifest, so the atlas can never
    grow; the only freedom is how many cells to fill. Blank placeholders are used during the
    binary search (identical byte size, no rasterisation) which keeps the search cheap, and the
    prefix is re-sorted by codepoint before serializing because the ALFT range table stores 6
    bytes per *contiguous run* — packing the kept set densely buys ~30 extra glyph slots.
    """
    def fits(n: int) -> bool:
        glyphs = {cp: font.glyphs.get(cp) or _blank_glyph(font) for cp in sorted(ranked_cps[:n])}
        trial = af.AlftFont(
            ver=font.ver,
            form=font.form,
            tag=font.tag,
            gw=font.gw,
            gh=font.gh,
            cols=font.cols,
            img_w=font.img_w,
            palette=font.palette,
            alig_meta=font.alig_meta,
            glyphs=glyphs,
        )
        try:
            af.build_alft(trial, target_size=target_size)
            return True
        except ValueError:
            return False

    if fits(len(ranked_cps)):
        return len(ranked_cps)
    lo, hi = 0, len(ranked_cps)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def build_chinese_alft(
    orig_alft_bytes: bytes,
    required_chars: Iterable[str],
    used_game_cps: Optional[Set[int]] = None,
    ttf_path: Optional[str] = None,
    fill_gb2312: bool = False,
    char_weights: Optional[Counter] = None,
    priority_cps: Optional[Set[int]] = None,
    secondary_priority_cps: Optional[Set[int]] = None,
) -> Tuple[bytes, Dict]:
    """
    Rebuild a fixed-size Aqualead ALFT bitmap font so that every character the client can
    actually display has a glyph.

    Priority (highest first):
      1. ASCII / kana / CJK punctuation  +  ``MUST_KEEP_UI_CHARS`` (server-pushed text)
      2. Every remaining codepoint found in the post-patch tables, the nested .aar story
         archives and the Aigis.exe UI literals, ranked by measured in-game frequency.
      3. (optional) speculative GB2312 filler — only with genuinely unused budget.

    The old implementation evicted "Japanese looking" slots in bulk (tier 2) and then filled the
    freed space with GB2312 filler characters that never appear in the game, which is exactly why
    「お詫び」「階層」「緊急」「兵舎」「預かり所」「選択」 rendered as red missing-glyph boxes.
    """
    ttf = find_chinese_ttf(ttf_path)
    target_size = len(orig_alft_bytes)
    font = af.parse_alft(orig_alft_bytes)
    orig_cps = set(font.glyphs.keys())

    zh_cps = {ord(c) for c in required_chars if 0x21 <= ord(c) <= 0xFFFF}
    required: Set[int] = set(zh_cps)
    if used_game_cps:
        required |= {cp for cp in used_game_cps if 0x21 <= cp <= 0xFFFF}
    required |= {ord(c) for c in MUST_KEEP_UI_CHARS}
    required = {cp for cp in required if 0x21 <= cp <= 0xFFFF}

    weights = char_weights or Counter()
    displayed: Set[int] = {cp for cp in (used_game_cps or set()) if 0x21 <= cp <= 0xFFFF}
    priority: Set[int] = {cp for cp in (priority_cps or set()) if 0x21 <= cp <= 0xFFFF}
    secondary: Set[int] = {cp for cp in (secondary_priority_cps or set()) if 0x21 <= cp <= 0xFFFF}

    always = required & _BASE_ALWAYS
    must = {ord(c) for c in MUST_KEEP_UI_CHARS} & required
    rest = required - always - must

    def rank(cp: int) -> Tuple[int, int, int, int]:
        # Tier 0: characters in whitelisted display columns — the player actually reads these.
        # Tier 1: characters only found in raw string pools (internal IDs, dead strings, trade
        #         item keys).  They must never outrank visible text for a glyph slot.
        # Within a tier: measured occurrence count, then characters present in the scanned
        # inventory, then codepoint order.
        if cp in priority:
            tier = 0            # whitelisted display columns — must never be evicted
        elif cp in secondary:
            tier = 1            # text in tables we do not translate (numbered tower tables, configs)
        elif cp in displayed:
            tier = 2            # raw string-pool characters (internal IDs, dead strings)
        else:
            tier = 3            # dictionary-only leftovers
        return (tier, -weights[cp], cp)

    ranked = sorted(always | must) + sorted(rest, key=rank)

    if fill_gb2312:
        ranked = ranked + [cp for cp in get_gb2312_level1_codepoints() if cp not in required]

    capacity = _fit_capacity(font, target_size, ranked)
    kept = sorted(ranked[:capacity])
    dropped = [cp for cp in ranked[capacity:] if cp in required]

    kept_set = set(kept)
    glyphs: Dict[int, Tuple[int, bytes]] = {}
    rendered = 0
    for cp in kept:
        g = font.glyphs.get(cp)
        if g is None:
            g = render_glyph_28x28(chr(cp), ttf)
            rendered += 1
        glyphs[cp] = g

    new_font = af.AlftFont(
        ver=font.ver,
        form=font.form,
        tag=font.tag,
        gw=font.gw,
        gh=font.gh,
        cols=font.cols,
        img_w=font.img_w,
        palette=font.palette,
        alig_meta=font.alig_meta,
        glyphs=glyphs,
    )
    out_bytes = af.build_alft(new_font, target_size=target_size)

    dropped_str = "".join(chr(cp) for cp in dropped)
    missing_displayed = [cp for cp in dropped if cp in displayed]
    missing_priority = [cp for cp in dropped if cp in priority]
    stats = {
        "orig_size": target_size,
        "final_size": len(out_bytes),
        "capacity": capacity,
        "required_codepoints": len(required),
        "displayed_codepoints": len(displayed),
        "priority_codepoints": len(priority),
        "secondary_codepoints": len(secondary),
        "final_glyphs": len(glyphs),
        "rendered_new_glyphs": rendered,
        "reused_original_glyphs": len(kept) - len([cp for cp in kept if cp not in orig_cps]),
        "added_required_sc": len([cp for cp in kept if cp not in orig_cps]),
        "added_bonus_gb2312": len([cp for cp in kept if cp not in required]),
        "dropped_low_priority": dropped,
        "dropped_low_priority_str": dropped_str,
        "missing_required": len(dropped),
        "missing_displayed": len(missing_displayed),
        "missing_priority": len(missing_priority),
        "missing_priority_str": "".join(chr(cp) for cp in missing_priority),
        "kept_used_game": len(displayed & kept_set),
        "total_used_game": len(displayed - set(range(0x21, 0x7F))),
        "ttf": os.path.basename(ttf),
    }
    return out_bytes, stats


def verify_glyph_coverage(alft_bytes: bytes, required_cps: Iterable[int]) -> List[int]:
    """Return the sorted list of required codepoints that have no glyph in `alft_bytes`."""
    have = set(af.parse_alft(alft_bytes).glyphs.keys())
    return sorted({cp for cp in required_cps if cp not in have})


def render_preview_png(alft_bytes: bytes, lines: List[str], out_png: str) -> None:
    """Render sample lines using the actual ALFT bitmap font to a PNG for visual verification."""
    font = af.parse_alft(alft_bytes)
    pad = 16
    line_h = 34
    max_w = max(sum((font.glyphs[ord(c)][0] if ord(c) in font.glyphs else 14) for c in line) for line in lines)
    img = Image.new("RGBA", (max_w + pad * 2, len(lines) * line_h + pad * 2), (24, 28, 42, 255))
    px = img.load()

    for li, line in enumerate(lines):
        cx = pad
        cy = pad + li * line_h
        for ch in line:
            cp = ord(ch)
            if cp == 0x20:
                cx += 10
                continue
            if cp == 0x3000:
                cx += 24
                continue
            g = font.glyphs.get(cp)
            if g is None:
                # Draw red missing box
                for y in range(2, 24):
                    for x in range(2, 22):
                        if y in (2, 23) or x in (2, 21):
                            px[cx + x, cy + y] = (255, 60, 60, 255)
                cx += 24
                continue
            adv, buf = g
            for y in range(font.gh):
                for x in range(font.gw):
                    a = buf[y * font.gw + x] * 17  # 0..15 -> 0..255
                    if a > 0 and 0 <= cx + x < img.width and 0 <= cy + y < img.height:
                        br, bg, bb, _ = px[cx + x, cy + y]
                        nr = (255 * a + br * (255 - a)) // 255
                        ng = (255 * a + bg * (255 - a)) // 255
                        nb = (255 * a + bb * (255 - a)) // 255
                        px[cx + x, cy + y] = (nr, ng, nb, 255)
            cx += adv

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png)
