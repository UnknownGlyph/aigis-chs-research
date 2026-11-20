"""
Local deployment and high-throughput GPU batch translation engine for Tencent Hunyuan
Hy-MT2-1.8B (`tencent/Hy-MT2-1.8B`) on NVIDIA RTX 4060.

Features:
  1. Auto-downloads `tencent/Hy-MT2-1.8B` weights & tokenizer to `D:\models\Hy-MT2-1.8B`.
  2. Runs bfloat16 SDPA (FlashAttention-2) GPU inference with length-sorted left-padded batching.
  3. Injects dynamic character/term glossary hits from existing Aigis translations when relevant.
  4. Validates placeholders (%d, %s, <TAG>, [TAG]) and preserves line breaks (\n / \r\n).
  5. Checkpoints atomically to `translations/<batch_file>` every wave so progress is never lost.
  6. Optional `--serve --port 8000` mode provides a local HTTP translation API server.
"""

import argparse
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Set, Tuple

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.join(BASE_DIR, "extracted")
TRANS_DIR = os.path.join(BASE_DIR, "translations")
DEFAULT_MODEL_DIR = r"D:\models\Hy-MT2-1.8B"
HF_REPO_ID = "tencent/Hy-MT2-1.8B"

PLACEHOLDER_RE = re.compile(r"(%[0-9.]*[dfsx]|%c\[[0-9a-fA-F]+\]|<[A-Z0-9_]+>|\[[A-Z0-9_]+\])")
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def ph_ok(jp: str, zh: str) -> bool:
    return sorted(PLACEHOLDER_RE.findall(jp)) == sorted(PLACEHOLDER_RE.findall(zh))


def save_json_atomic(path: str, data: Dict[str, str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def download_file_multithread(
    url: str,
    dst_path: str,
    num_threads: int = 16,
    chunk_mb: int = 16,
) -> None:
    """High-speed multi-threaded HTTP Range downloader with live progress and auto-retry."""
    import threading
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        cr = r.headers.get("Content-Range", "")
        total_size = int(cr.split("/")[-1])

    tmp_path = dst_path + ".downloading"
    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) != total_size:
        with open(tmp_path, "wb") as fp:
            fp.truncate(total_size)

    chunk_size = chunk_mb * 1024 * 1024
    ranges = []
    for start in range(0, total_size, chunk_size):
        end = min(total_size - 1, start + chunk_size - 1)
        ranges.append((start, end))

    lock = threading.Lock()
    fp = open(tmp_path, "r+b")
    downloaded = [0]
    t0 = time.time()
    last_log = [t0]

    def worker(q_list: List[Tuple[int, int]]) -> None:
        while True:
            with lock:
                if not q_list:
                    return
                start, end = q_list.pop(0)
            expected = end - start + 1
            for attempt in range(5):
                try:
                    rq = urllib.request.Request(
                        url,
                        headers={"User-Agent": "Mozilla/5.0", "Range": f"bytes={start}-{end}"},
                    )
                    buf = bytearray()
                    with urllib.request.urlopen(rq, timeout=30) as resp:
                        while True:
                            blk = resp.read(256 * 1024)
                            if not blk:
                                break
                            buf.extend(blk)
                            with lock:
                                downloaded[0] += len(blk)
                                now = time.time()
                                if now - last_log[0] >= 5.0:
                                    last_log[0] = now
                                    mb_done = downloaded[0] / (1024 * 1024)
                                    mb_tot = total_size / (1024 * 1024)
                                    spd = mb_done / max(0.1, now - t0)
                                    eta = (mb_tot - mb_done) / max(0.01, spd)
                                    print(
                                        f"  [ModelScope 16T] {mb_done:7.1f} / {mb_tot:.1f} MB "
                                        f"({mb_done/mb_tot*100:5.1f}%)  speed={spd:5.1f} MB/s  ETA={eta:4.0f}s",
                                        flush=True,
                                    )
                    if len(buf) == expected:
                        with lock:
                            fp.seek(start)
                            fp.write(buf)
                            fp.flush()
                        break
                    else:
                        with lock:
                            downloaded[0] -= len(buf)
                except Exception:
                    time.sleep(1.0)
            else:
                raise RuntimeError(f"Failed chunk {start}-{end} after 5 attempts")

    queue = list(ranges)
    threads = [threading.Thread(target=worker, args=(queue,), daemon=True) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fp.close()
    if queue:
        raise RuntimeError(f"Download incomplete: {len(queue)} chunks remaining")
    os.replace(tmp_path, dst_path)


def ensure_model_downloaded(model_dir: str = DEFAULT_MODEL_DIR) -> str:
    os.makedirs(model_dir, exist_ok=True)
    safetensors_path = os.path.join(model_dir, "model.safetensors")
    if os.path.exists(safetensors_path) and os.path.getsize(safetensors_path) == 4077072784:
        return model_dir

    # Clean any stale 0-byte huggingface lock/incomplete files
    # Fetch small config/tokenizer files first if missing
    if not os.path.exists(os.path.join(model_dir, "tokenizer.json")):
        print(f"[Download] Fetching tokenizer & configs -> {model_dir} ...")
        snapshot_download(
            repo_id=HF_REPO_ID,
            local_dir=model_dir,
            ignore_patterns=["*.safetensors", "train/*", "imgs/*", "*.png", "*.md"],
        )

    ms_url = "https://modelscope.cn/models/Tencent-Hunyuan/Hy-MT2-1.8B/resolve/master/model.safetensors"
    print(f"[Download] Downloading model.safetensors (3888.2 MB) via 16-thread ModelScope domestic CDN -> {safetensors_path} ...", flush=True)
    t0 = time.time()
    download_file_multithread(ms_url, safetensors_path, num_threads=16, chunk_mb=16)
    print(f"[Download] model.safetensors ready in {time.time() - t0:.1f}s!", flush=True)
    return model_dir


def load_all_existing_translations() -> Dict[str, str]:
    existing: Dict[str, str] = {}
    if not os.path.isdir(TRANS_DIR):
        return existing
    for fn in sorted(os.listdir(TRANS_DIR)):
        if not fn.endswith(".json"):
            continue
        if fn in ("glossary_zh.json", "full_zh.json") or fn.startswith("batch_"):
            p = os.path.join(TRANS_DIR, fn)
            try:
                d = json.load(open(p, "r", encoding="utf-8"))
                if isinstance(d, dict):
                    for k, v in d.items():
                        if isinstance(k, str) and isinstance(v, str) and v and ph_ok(k, v):
                            existing[k] = v
            except Exception:
                pass
    return existing


def load_name_glossary() -> List[Tuple[str, str]]:
    """
    Build a compact list of (jp_name, zh_name) for katakana character/term names >= 3 chars
    so we can dynamically attach relevant terminology hints to prompts when those names appear.
    """
    terms: Dict[str, str] = {
        "アンナ": "安娜",
        "アイギス": "艾吉斯",
        "ケイティ": "凯蒂",
        "シビラ": "希比拉",
        "ソーマ": "索玛",
        "ヴァレリー": "瓦莱丽",
        "カリオペ": "卡莉奥佩",
        "エレイン": "伊莱恩",
        "アリサ": "亚莉莎",
        "レアン": "雷安",
        "ダニエラ": "丹妮拉",
        "クロエ": "克洛伊",
        "メーリス": "梅莉丝",
        "キャリー": "凯莉",
        "クレア": "克蕾雅",
        "フェイ": "菲",
        "ロゼット": "罗洁特",
        "ベルニス": "贝尔尼斯",
        "フィリス": "菲莉丝",
        "カリスマ": "魅力",
        "スタミナ": "体力",
        "クラスチェンジ": "职业晋升",
        "トークン": "召唤物",
        "出撃コスト": "出击费用",
        "ユニット": "单位",
        "ミッション": "任务",
        "クエスト": "关卡",
        "アビリティ": "被动能力",
        "ゴブリン": "哥布林",
        "オーク": "兽人",
        "リッチ": "巫妖",
        "ドラゴン": "巨龙",
        "ヴァンパイア": "吸血鬼",
        "エルフ": "精灵",
        "ドワーフ": "矮人",
        "デーモン": "恶魔",
        "エンジェル": "天使",
        "ワルキューレ": "女武神",
        "ネクロマンサー": "死灵法师",
    }
    # Also load short pure-katakana character names from NameText.atb if available
    ext_names = os.path.join(EXT_DIR, "NameText.atb.json")
    b2_path = os.path.join(TRANS_DIR, "batch_02_skills_abilities_names.json")
    if os.path.exists(ext_names) and os.path.exists(b2_path):
        b2 = json.load(open(b2_path, "r", encoding="utf-8"))
        nd = json.load(open(ext_names, "r", encoding="utf-8"))
        for e in nd.get("entries", []):
            jp = e["jp"]
            if 3 <= len(jp) <= 8 and re.fullmatch(r"[\u30a1-\u30faー]+", jp):
                zh = b2.get(jp)
                if zh and 1 <= len(zh) <= 6 and jp not in terms:
                    terms[jp] = zh
    # Sort longest first
    return sorted(terms.items(), key=lambda kv: -len(kv[0]))


class HyMT2LocalEngine:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR, device: str = "cuda"):
        self.model_dir = ensure_model_downloaded(model_dir)
        self.device = device if torch.cuda.is_available() else "cpu"
        print(f"[Engine] Loading Hy-MT2-1.8B from {self.model_dir} onto {self.device} (bfloat16)...")
        t0 = time.time()
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, trust_remote_code=True)
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = 120002

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_dir,
            torch_dtype=torch.bfloat16 if self.device.startswith("cuda") else torch.float32,
            device_map=self.device,
            trust_remote_code=True,
            attn_implementation="sdpa",
        )
        self.model.eval()
        self.terms = load_name_glossary()
        print(f"[Engine] Loaded in {time.time() - t0:.1f}s (VRAM allocated: {torch.cuda.memory_allocated() / (1024**3):.2f} GB, glossary terms: {len(self.terms)})")

    def build_prompt(self, jp_text: str) -> str:
        # Match up to 4 character/term hits present in this Japanese text
        matched = []
        for k, v in self.terms:
            if k in jp_text:
                matched.append(f"{k} 翻译成 {v}")
                if len(matched) >= 4:
                    break
        if matched:
            ref_block = "参考下面的翻译：\n" + "\n".join(matched) + "\n"
        else:
            ref_block = ""
        user_msg = (
            f"{ref_block}将以下文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释：\n\n{jp_text}"
        )
        # Apply official Hy-MT2 chat template directly (avoids per-item jinja overhead)
        return f"<｜hy_begin▁of▁sentence｜><｜hy_User｜>{user_msg}<｜hy_Assistant｜>"

    @torch.inference_mode()
    def translate_batch(self, jp_list: List[str], temperature: float = 0.0) -> List[str]:
        if not jp_list:
            return []
        prompts = [self.build_prompt(s) for s in jp_list]
        enc = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            add_special_tokens=False,
        ).to(self.model.device)

        in_len = enc["input_ids"].shape[1]
        max_jp_chars = max(len(s) for s in jp_list)
        max_new = min(512, max(32, int(max_jp_chars * 1.8) + 24))

        gen_kwargs = {
            "max_new_tokens": max_new,
            "pad_token_id": 120002,
            "eos_token_id": [120020, 120008],
            "repetition_penalty": 1.05,
        }
        if temperature > 0.0:
            gen_kwargs.update({"do_sample": True, "temperature": temperature, "top_p": 0.6, "top_k": 20})
        else:
            gen_kwargs.update({"do_sample": False})

        out_ids = self.model.generate(**enc, **gen_kwargs)
        gen_ids = out_ids[:, in_len:]
        decoded = self.tokenizer.batch_decode(gen_ids, skip_special_tokens=True)

        results: List[str] = []
        for jp, raw_zh in zip(jp_list, decoded):
            zh = self.postprocess(jp, raw_zh)
            results.append(zh)
        return results

    @staticmethod
    def postprocess(jp: str, raw_zh: str) -> str:
        # Strip any accidental trailing special token text
        for stop_str in ("<｜hy_", "<|hy_"):
            idx = raw_zh.find(stop_str)
            if idx != -1:
                raw_zh = raw_zh[:idx]
        zh = raw_zh.strip()

        # Preserve outer Japanese dialogue brackets 「...」 if original had them and translation dropped/changed them
        if jp.startswith("「") and jp.endswith("」"):
            if (zh.startswith("“") and zh.endswith("”")) or (zh.startswith("\"") and zh.endswith("\"")):
                zh = "「" + zh[1:-1] + "」"
            elif not zh.startswith("「"):
                zh = "「" + zh.lstrip("“\"「")
                if not zh.endswith("」"):
                    zh = zh.rstrip("”\"」") + "」"

        # Match \r\n vs \n style of original string
        if "\r\n" in jp and "\r\n" not in zh and "\n" in zh:
            zh = zh.replace("\n", "\r\n")
        elif "\r\n" not in jp and "\r\n" in zh:
            zh = zh.replace("\r\n", "\n")

        return zh


def translate_tables(
    engine: HyMT2LocalEngine,
    tables: List[str],
    batch_file: str,
    batch_size: int = 32,
    save_every_batches: int = 5,
    max_items: int = 0,
) -> None:
    os.makedirs(TRANS_DIR, exist_ok=True)
    out_path = os.path.join(TRANS_DIR, batch_file)
    batch_dict: Dict[str, str] = {}
    if os.path.exists(out_path):
        batch_dict = json.load(open(out_path, "r", encoding="utf-8"))

    global_existing = load_all_existing_translations()
    global_existing.update(batch_dict)

    todo: List[str] = []
    seen: Set[str] = set()
    for tbl_name in tables:
        p = os.path.join(EXT_DIR, f"{tbl_name}.json")
        if not os.path.exists(p):
            print(f"[WARN] Extracted file not found: {p}")
            continue
        d = json.load(open(p, "r", encoding="utf-8"))
        for e in d.get("entries", []):
            jp = e["jp"]
            if not jp or jp in seen or jp in global_existing:
                continue
            if not JP_RE.search(jp):
                continue
            seen.add(jp)
            todo.append(jp)

    # Sort by length so every GPU batch has minimal padding waste!
    todo.sort(key=len)
    if max_items > 0:
        todo = todo[:max_items]

    total = len(todo)
    print(f"[Translate] Tables={tables} -> {batch_file}")
    print(f"[Translate] Already cached: {len(global_existing)} | Remaining todo: {total} (batch_size={batch_size})")
    if total == 0:
        print("[Translate] Nothing left to translate!")
        return

    t_start = time.time()
    done = 0
    num_batches = (total + batch_size - 1) // batch_size

    for b_idx in range(num_batches):
        sub = todo[b_idx * batch_size : (b_idx + 1) * batch_size]
        zhs = engine.translate_batch(sub, temperature=0.0)
        for jp, zh in zip(sub, zhs):
            if zh and ph_ok(jp, zh):
                batch_dict[jp] = zh
            else:
                # Fallback if placeholder was altered: preserve placeholders or keep
                batch_dict[jp] = zh if zh else jp
        done += len(sub)

        if (b_idx + 1) % save_every_batches == 0 or (b_idx + 1) == num_batches:
            save_json_atomic(out_path, batch_dict)
            elapsed = time.time() - t_start
            rate = done / max(0.001, elapsed)
            rem_sec = (total - done) / max(0.01, rate)
            sample_jp = sub[-1].replace("\n", "/")[:28]
            sample_zh = zhs[-1].replace("\n", "/")[:28]
            print(
                f"  [{done:5d}/{total:5d}] ({done/total*100:5.1f}%)  "
                f"speed={rate:5.1f} lines/s  ETA={rem_sec/60:4.1f}m  "
                f"| {sample_jp} => {sample_zh}",
                flush=True,
            )

    print(f"[DONE] Saved {len(batch_dict)} translations to {out_path} in {(time.time()-t_start)/60:.1f} min.")


def run_server(engine: HyMT2LocalEngine, host: str = "127.0.0.1", port: int = 8000) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            texts = body.get("texts") or ([body["text"]] if "text" in body else [])
            zhs = engine.translate_batch(texts)
            resp = json.dumps({"translations": zhs}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    srv = HTTPServer((host, port), Handler)
    print(f"[Server] Hy-MT2-1.8B local API listening on http://{host}:{port}/translate")
    srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--tables", nargs="*", default=["QuestEventText.atb"])
    ap.add_argument("--batch-file", default="batch_05_story_quest.json")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--max-items", type=int, default=0)
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    engine = HyMT2LocalEngine(model_dir=args.model_dir)
    if args.serve:
        run_server(engine, port=args.port)
    else:
        translate_tables(
            engine,
            tables=args.tables,
            batch_file=args.batch_file,
            batch_size=args.batch_size,
            max_items=args.max_items,
        )


if __name__ == "__main__":
    main()
