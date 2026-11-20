"""
Build Chinese-capable Aqualead ALFT bitmap fonts (MainFont.aft & MainFontFix.aft)
with exact original file sizes so Aigis.exe accepts them without any binary modification.

Strategy:
  1. Preserve 100% of original glyphs for ASCII, punctuation, Kana, and all Japanese Kanji
     actually referenced by game tables.
  2. Replace unused slots (Cyrillic, Greek, unused JIS Level-2 kanji) with crisp 28x28 4bpp
     Simplified Chinese glyphs rendered via Windows Microsoft YaHei Bold (msyhbd.ttc),
     calibrated to the exact advance width (24px) and ink box (x[0..23], y[0..23]) of
     Aigis's native glyphs.
  3. Pad trailing zeros to match exact original byte size (1,727,372 B / 1,618,424 B).
"""

import os
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


def collect_used_game_codepoints(game_dir: str, patch_out_dir: Optional[str] = None) -> Set[int]:
    """
    Collect all codepoints >= 0x21 actually present in effective post-patch .cache ALTB/ALAR files.
    When patch_out_dir is provided, reads patched files in preference to originals so Japanese-only
    kanji replaced by Chinese translations automatically free up glyph slots.
    """
    cache_dir = os.path.join(game_dir, ".cache")
    patch_cache = os.path.join(patch_out_dir, ".cache") if patch_out_dir else None
    used: Set[int] = set()
    # Always keep ASCII + Japanese Kana + basic fullwidth punctuation
    for cp in range(0x21, 0x7F):
        used.add(cp)
    for cp in range(0x3000, 0x30FF):
        used.add(cp)
    for cp in range(0xFF01, 0xFF60):
        used.add(cp)

    for fn in os.listdir(cache_dir):
        if fn.endswith(".md5"):
            continue
        p = os.path.join(patch_cache, fn) if (patch_cache and os.path.exists(os.path.join(patch_cache, fn))) else os.path.join(cache_dir, fn)
        raw = open(p, "rb").read()
        payload = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        if payload[:4] == b"ALTB" and (payload[5] & 0x04):
            tbl = af.parse_altb(payload)
            txt = tbl.string_pool.decode("utf-8", errors="ignore")
            for ch in txt:
                cp = ord(ch)
                if 0x21 <= cp <= 0xFFFF:
                    used.add(cp)
    return used


def build_chinese_alft(
    orig_alft_bytes: bytes,
    required_chars: Iterable[str],
    used_game_cps: Set[int],
    ttf_path: Optional[str] = None,
    fill_gb2312: bool = True,
) -> Tuple[bytes, Dict]:
    """
    Inject required Simplified Chinese glyphs (plus optional extra GB2312-L1 glyphs)
    into an ALFT font while keeping ALL required translated chars + ASCII + Kana + as many
    used original Japanese glyphs as fit inside exact original file byte size.
    """
    ttf = find_chinese_ttf(ttf_path)
    target_size = len(orig_alft_bytes)
    font = af.parse_alft(orig_alft_bytes)
    orig_cps = set(font.glyphs.keys())

    # Required codepoints: ALL translated chars + ASCII + basic punctuation
    ascii_and_punct = set(range(0x21, 0x7F)) | {0x3001, 0x3002, 0x300C, 0x300D, 0x300E, 0x300F, 0x3010, 0x3011}
    req_cps = {ord(c) for c in required_chars if 0x21 <= ord(c) <= 0xFFFF} | (ascii_and_punct & orig_cps)
    missing_req = sorted(req_cps - orig_cps)

    # Eviction priority:
    #   Tier 0 (evict first): Cyrillic/Greek/misc symbols not in used_game_cps or req_cps
    #   Tier 1: Unused original glyphs (not in used_game_cps or req_cps)
    #   Tier 2 (only if still tight): Used original JP kanji NOT in req_cps and NOT ASCII/Kana
    unused_orig = orig_cps - used_game_cps - req_cps
    used_nonreq_jp = (orig_cps & used_game_cps) - req_cps - set(range(0x21, 0x7F)) - set(range(0x3000, 0x30FF))

    evict_tier01 = sorted(
        unused_orig,
        key=lambda cp: (
            0 if (0x00A0 <= cp <= 0x04FF or 0x2000 <= cp <= 0x2FFF) else 1,
            -cp,
        ),
    )
    evict_tier2 = sorted(used_nonreq_jp, reverse=True)
    evict_order = evict_tier01 + evict_tier2

    # Reserve generous room for range table + widths + ALIG header
    max_alig_bytes = target_size - 32000 - 96
    max_rows = max_alig_bytes // (font.img_w * font.gh // 2)
    max_glyphs = max_rows * font.cols

    kept_glyphs = dict(font.glyphs)

    # Evict lowest-priority glyphs if needed to accommodate all missing_req
    need_total = len(kept_glyphs) + len(missing_req)
    evicted = 0
    if need_total > max_glyphs:
        to_drop = need_total - max_glyphs
        for cp in evict_order[:to_drop]:
            if cp in kept_glyphs:
                del kept_glyphs[cp]
                evicted += 1
        evict_order = evict_order[to_drop:]

    # Render and inject ALL required Chinese glyphs (100% guaranteed)
    added_req = 0
    for cp in missing_req:
        kept_glyphs[cp] = render_glyph_28x28(chr(cp), ttf)
        added_req += 1

    # Pre-fill remaining free slots (and remaining Tier-0/1 unused slots ONLY) with high-freq GB2312 chars
    remaining_unused = [cp for cp in evict_tier01 if cp in kept_glyphs]
    added_bonus = 0
    if fill_gb2312:
        gb1_missing = [cp for cp in get_gb2312_level1_codepoints() if cp not in kept_glyphs]
        safe_cap = max_glyphs - 18
        for cp in gb1_missing:
            if len(kept_glyphs) >= safe_cap:
                if remaining_unused:
                    drop_cp = remaining_unused.pop(0)
                    if drop_cp in kept_glyphs:
                        del kept_glyphs[drop_cp]
                        evicted += 1
                else:
                    break
            kept_glyphs[cp] = render_glyph_28x28(chr(cp), ttf)
            added_bonus += 1

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
        glyphs=kept_glyphs,
    )

    bonus_added_list = [cp for cp in kept_glyphs if cp not in orig_cps and cp not in req_cps]
    extra_evict = [cp for cp in evict_order if cp in kept_glyphs and cp not in req_cps]
    while True:
        try:
            out_bytes = af.build_alft(new_font, target_size=target_size)
            break
        except ValueError:
            if bonus_added_list:
                for _ in range(min(18, len(bonus_added_list))):
                    del new_font.glyphs[bonus_added_list.pop()]
                    added_bonus -= 1
            elif extra_evict:
                for _ in range(min(18, len(extra_evict))):
                    del new_font.glyphs[extra_evict.pop(0)]
                    evicted += 1
            else:
                raise

    stats = {
        "orig_size": target_size,
        "final_size": len(out_bytes),
        "orig_glyphs": len(orig_cps),
        "final_glyphs": len(new_font.glyphs),
        "added_required_sc": added_req,
        "added_bonus_gb2312": added_bonus,
        "evicted_unused": evicted,
        "kept_used_game": len(used_game_cps & set(new_font.glyphs.keys())),
        "total_used_game": len(used_game_cps & orig_cps),
        "ttf": os.path.basename(ttf),
    }
    return out_bytes, stats


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
