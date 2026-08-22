# -*- coding: utf-8 -*-
"""Worker OmniVoice — chạy bằng PYTHON CÓ torch+omnivoice (venv gói GPU / máy dev).

Nạp model + Whisper 1 LẦN rồi phục vụ tổng hợp giọng qua HTTP nội bộ (127.0.0.1):
  GET  /health                  -> {"ready": bool, "error": str}
  POST /synth  {text, voice...}  -> audio/wav (PCM16) | {"error": ...}

Engine `omnivoice:` trong tool chính (không có torch) khởi động worker này và gọi nó.
Tái dùng lõi đã kiểm nghiệm của PeiPeiCloneVoice (app.engine / app.profiles).
Tự thoát khi cha chết-lâu (idle-timeout) để không để tiến trình GPU mồ côi.

★07/08 GỘP LÔ (`--batch N`, mặc định 4) — lane "cắt giờ":
  Trước: mỗi request tự ôm `gen_lock` gọi model cho ĐÚNG MỘT câu ⇒ 4 luồng của tool xếp hàng
  sau ổ khoá, GPU chỉ 35-39%. Nay mọi request xếp vào một HÀNG CHỜ và MỘT luồng sinh duy nhất
  gom tối đa `--batch` câu (CÙNG giọng/tham số) trong cửa sổ `--batch-wait-ms` rồi gọi
  `model.generate(text=[...])` một lượt.
  VÌ SAO ĂN: vòng giải mã chạy ĐÚNG `num_step` (=32) lượt forward cho CẢ LÔ
  (omnivoice/models/omnivoice.py:1384) ⇒ gộp 4 câu thì số lượt forward giảm 4 lần.
  KHÔNG LÂY GIỌNG: mặt nạ chú ý dựng theo TỪNG HÀNG (`batch_attention_mask[i,:,:c_len,:c_len]`)
  nên câu i không có một ô True nào trỏ sang câu j; `voice_clone_prompt` nằm trong `input_ids`
  của từng hàng, không dùng chung.
  Đo E2E qua đúng đường sản xuất (64 câu thật): 2,47× và 2,97× · audio hợp lệ 448/448 ·
  máy nghe lại (Whisper large-v3) 63/64 ⟷ 63/64, DANH SÁCH CÂU GIỐNG HỆT.
  🔴 `--batch 1` = TẮT HẲN, chạy lại ĐÚNG đường cũ (không qua hàng chờ) — đường lùi an toàn.
  Hợp đồng HTTP KHÔNG đổi (POST /synth 1 câu → 1 WAV) nên client không phải sửa gì."""
import argparse
import io
import json
import os
import queue
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ⚠ Script này nằm cạnh bilisub/tts/omnivoice.py. Khi chạy trực tiếp bằng python, thư mục
# chứa script lọt vào sys.path[0] → `from omnivoice import OmniVoice` (trong app.engine) sẽ
# vớ NHẦM file omnivoice.py client thay vì package 'omnivoice' đã cài. Gỡ thư mục này khỏi
# sys.path để import đúng package pip.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]

# 🔴★29/07 KHÁCH BÁO LỖI THẬT trên 1.5.30:
#     LỖI: Không tạo được segment audio nào — Sinh giọng clone lỗi:
#     'charmap' codec can't encode character 'ỏ' ...      ('ỏ' = chữ "ỏ")
# Windows mặc định stdout = cp1252. Bất kỳ dòng in/log nào chạm chữ tiếng Việt (lõi app
# in tên giọng / câu đang đọc) đều NÉM UnicodeEncodeError, và nó nổ NGAY TRONG khối
# try của /synth ⇒ trả 500 ⇒ tool báo "không tạo được segment audio nào".
# MÁY DEV KHÔNG BAO GIỜ THẤY vì luôn chạy với PYTHONUTF8=1 — kể cả bài thử "giả lập máy
# khách" cũng thừa hưởng biến đó, nên nó lọt qua mọi vòng kiểm (xem quy tắc 47/51).
# Ép UTF-8 NGAY TỪ ĐẦU, không phụ thuộc biến môi trường của máy khách. `errors="replace"`
# để một dòng log xấu KHÔNG BAO GIỜ giết được việc sinh giọng nữa.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — stream lạ (không phải TextIO) thì bỏ qua
        pass

STATE = {
    "ready": False, "error": "", "eng": None, "pm": None,
    "prompts": {}, "gen_lock": threading.Lock(), "last": time.time(),
    # ★07/08 gộp lô — batch_max 1 = TẮT (đường cũ nguyên vẹn)
    "q": queue.Queue(), "batch_max": 1, "wait_s": 0.030,
    "stat_batches": 0, "stat_items": 0,
}


def _batch_helpers_ok() -> bool:
    """Lõi PeiPeiCloneVoice có đủ hàm để hậu kỳ lô GIỐNG HỆT đường 1-câu-một-lượt không?

    Gộp lô phải chép ĐÚNG hậu kỳ của `app.engine.VoiceEngine.generate()` (tách câu con →
    fade nối → `_finalize_audio`). Bản CloneVoice cũ/mới thiếu một hàm là audio ra sẽ KHÁC —
    thà tụt về đường 1 câu (chậm như cũ) còn hơn ra tiếng khác.
    """
    try:
        from app.engine import (_split_sentences, _finalize_audio,  # noqa: F401
                                _apply_fade)
        return callable(getattr(STATE["eng"], "_base_gen_kwargs", None))
    except Exception:  # noqa: BLE001
        return False


def _load_models(args):
    """Nạp OmniVoice + Whisper (chạy nền để /health trả lời được ngay lúc đang nạp)."""
    try:
        sys.path.insert(0, args.app_dir)
        if args.model_dir:
            os.environ["OMNIVOICE_MODEL_DIR"] = args.model_dir
        if args.asr_dir:
            os.environ["OMNIVOICE_ASR_DIR"] = args.asr_dir
        # ★29/07 BỎ WHISPER KHI CHỈ DÙNG GIỌNG LÀM SẴN — cắt 1,51 GB khỏi gói khách tải.
        # Whisper chỉ cần khi TẠO giọng mới (nghe file mẫu để lấy lời thoại) và ở bước tự
        # chấm điểm. Tool chỉ giao GIỌNG LÀM SẴN (.pt) nên khách không bao giờ cần nó.
        # `app.engine.load()` ghim cứng load_asr=True, mà đó là code của app KHÁC (dùng
        # chung) nên KHÔNG sửa vào đó — chặn ngay ở tầng thư viện cho gọn và không phá app kia.
        if getattr(args, "no_asr", False):
            try:
                import omnivoice as _ov
                _orig_fp = _ov.OmniVoice.from_pretrained

                def _fp_no_asr(*a, **kw):
                    kw["load_asr"] = False
                    kw.pop("asr_model_name", None)
                    return _orig_fp(*a, **kw)

                _ov.OmniVoice.from_pretrained = staticmethod(_fp_no_asr)
                print("[omni] chạy KHÔNG kèm Whisper (chỉ đọc giọng làm sẵn)", flush=True)
            except Exception as ex:  # noqa: BLE001 — không chặn được thì cứ nạp như cũ
                print(f"[omni] không bỏ được Whisper ({ex}) — nạp đầy đủ", flush=True)
        from app.engine import VoiceEngine
        from app.profiles import ProfileManager
        eng = VoiceEngine()
        eng.load(log=lambda m: print("[omni]", m, flush=True))
        pm = ProfileManager()
        if args.voices_dir:
            pm.voices_dir = args.voices_dir     # kho .pt giọng clone (ghi đè mặc định)
        STATE["eng"] = eng
        STATE["pm"] = pm
        # ★07/08 chốt chặn gộp lô: thiếu hàm hậu kỳ của lõi CloneVoice ⇒ TỰ TẮT, chạy đường cũ
        if STATE["batch_max"] > 1 and not _batch_helpers_ok():
            STATE["batch_max"] = 1
            print("[omni] ⚠ lõi CloneVoice thiếu hàm hậu kỳ → TẮT gộp lô, chạy từng câu",
                  flush=True)
        STATE["ready"] = True
        print(f"[omni] READY (gộp lô tối đa {STATE['batch_max']} câu/lượt)"
              if STATE["batch_max"] > 1 else "[omni] READY", flush=True)
    except Exception as e:                       # noqa: BLE001
        STATE["error"] = f"{e}\n{traceback.format_exc()}"[:1500]
        print("[omni] LOAD FAIL:", STATE["error"], flush=True)


def _get_prompt(voice: str):
    """Nạp voice-clone prompt theo TÊN giọng (kho .pt) hoặc theo ĐƯỜNG DẪN .pt — có cache."""
    p = STATE["prompts"].get(voice)
    if p is not None:
        return p
    if os.path.isfile(voice) and voice.lower().endswith(".pt"):
        from app.profiles import _load_pt, _as_prompt
        p = _as_prompt(_load_pt(voice))
    else:
        p = STATE["pm"].load_prompt(voice)
    STATE["prompts"][voice] = p
    return p


# ──────────────────── ★07/08 GỘP LÔ: hàng chờ + MỘT luồng sinh duy nhất ────────────────────
class _Job:
    __slots__ = ("text", "key", "ev", "wav", "err")

    def __init__(self, text, key):
        self.text = text
        self.key = key            # (voice, language, speed, num_step, guidance)
        self.ev = threading.Event()
        self.wav = None
        self.err = ""


def _synth_group(key, texts):
    """Sinh MỘT LÔ. Trả list audio (đã hậu kỳ) — CÙNG THỨ TỰ `texts`.

    Chép ĐÚNG logic `app.engine.VoiceEngine.generate()` (tách câu con → sinh → fade nối →
    `_finalize_audio`) để audio ra KHÔNG khác đường 1-câu-một-lượt. `breath_reduce` mặc định
    0 nên `_reduce_breath` là hàm rỗng (`if strength <= 0: return audio`) — không cần chép.
    """
    import numpy as np
    from app.engine import _split_sentences, _finalize_audio, _apply_fade

    voice, lang, speed, num_step, guidance = key
    eng = STATE["eng"]
    sr = eng.sample_rate
    prompt = _get_prompt(voice)
    base = eng._base_gen_kwargs(
        num_step=num_step, language=lang, speed=speed,
        guidance_scale=guidance, voice_clone_prompt=prompt)

    # trải phẳng câu con của TẤT CẢ request trong lô
    owner, flat = [], []
    for i, t in enumerate(texts):
        subs = _split_sentences(t, lang) or [t.strip()]
        for s in subs:
            owner.append(i)
            flat.append(s)

    pieces = eng.model.generate(text=flat, **base)

    out = [None] * len(texts)
    buf = [[] for _ in texts]
    for oi, a in zip(owner, pieces):
        buf[oi].append(np.asarray(a, dtype=np.float32))
    for i, parts in enumerate(buf):
        if len(parts) == 1:
            audio = parts[0]
        else:
            # nhiều câu con: fade nhẹ 2 đầu MỖI đoạn rồi nối — y hệt engine.generate()
            audio = np.concatenate([_apply_fade(p, sr, min(8.0, 10.0)) for p in parts])
        audio, _ = _finalize_audio(audio, sr, None, -16.0, True, 10.0)
        out[i] = audio
    return out


def _wav_bytes(audio):
    import soundfile as sf
    bio = io.BytesIO()
    sf.write(bio, audio, STATE["eng"].sample_rate, format="WAV", subtype="PCM_16")
    return bio.getvalue()


def _run_batch(key, jobs):
    """Sinh lô; lô hỏng → LÙI VỀ TỪNG CÂU (một câu 'độc' không được giết cả lô)."""
    try:
        outs = _synth_group(key, [j.text for j in jobs])
        for j, a in zip(jobs, outs):
            j.wav = _wav_bytes(a)
    except Exception as ex_batch:  # noqa: BLE001
        if len(jobs) == 1:
            jobs[0].err = f"{ex_batch}"[:400]
        else:
            print(f"[omni] ⚠ lô {len(jobs)} câu hỏng ({str(ex_batch)[:120]}) "
                  f"→ sinh lại từng câu", flush=True)
            for j in jobs:
                try:
                    j.wav = _wav_bytes(_synth_group(key, [j.text])[0])
                except Exception as ex:  # noqa: BLE001
                    j.err = f"{ex}"[:400]
    finally:
        STATE["stat_batches"] += 1
        STATE["stat_items"] += len(jobs)
        for j in jobs:
            j.ev.set()


def _gen_once(Q, pending):
    """Gom MỘT lô rồi sinh. Tách riêng để lỗi bất ngờ không giết luồng sinh."""
    if not pending:
        j = Q.get()                      # chưa có gì → chờ vô hạn
        pending.setdefault(j.key, []).append(j)
    # gom thêm trong cửa sổ ngắn cho đến khi đủ lô
    t_end = time.time() + STATE["wait_s"]
    while max((len(v) for v in pending.values()), default=0) < STATE["batch_max"]:
        left = t_end - time.time()
        if left <= 0:
            break
        try:
            j = Q.get(timeout=left)
        except queue.Empty:
            break
        pending.setdefault(j.key, []).append(j)
    # chọn nhóm ĐÔNG NHẤT (cùng giọng/tham số) để gộp
    key = max(pending, key=lambda k: len(pending[k]))
    jobs = pending[key][:STATE["batch_max"]]
    pending[key] = pending[key][STATE["batch_max"]:]
    if not pending[key]:
        del pending[key]
    with STATE["gen_lock"]:              # model KHÔNG thread-safe → vẫn tuần tự hoá
        _run_batch(key, jobs)
    STATE["last"] = time.time()


def _gen_loop():
    """MỘT luồng sinh duy nhất (thay cho gen_lock quanh mỗi câu).

    ⚠ Luồng này CHẾT = mọi request treo vĩnh viễn ⇒ bắt mọi lỗi, đánh thức job đang chờ."""
    Q = STATE["q"]
    pending: dict = {}
    while True:
        try:
            _gen_once(Q, pending)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            for jobs in pending.values():
                for j in jobs:
                    j.err = "luồng sinh gặp lỗi nội bộ"
                    j.ev.set()
            pending.clear()
            time.sleep(0.2)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # ★07/08 keep-alive: khỏi mở TCP mới cho mỗi câu

    def log_message(self, *a):        # tắt log mặc định (ồn)
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        STATE["last"] = time.time()
        if self.path == "/health":
            self._json(200, {"ready": STATE["ready"], "error": STATE["error"]})
        elif self.path == "/stats":       # ★07/08 đếm lô (để nghiệm thu gộp lô có ăn không)
            self._json(200, {"batches": STATE["stat_batches"],
                             "items": STATE["stat_items"],
                             "batch_max": STATE["batch_max"]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        STATE["last"] = time.time()
        if self.path != "/synth":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:        # noqa: BLE001
            return self._json(400, {"error": f"bad request: {e}"})
        if not STATE["ready"]:
            return self._json(503, {"error": STATE["error"] or "model chưa nạp xong"})
        text = (req.get("text") or "").strip()
        voice = (req.get("voice") or "").strip()
        if not text or not voice:
            return self._json(400, {"error": "thiếu text/voice"})
        # ★07/08 GỘP LÔ: đi qua hàng chờ. `--batch 1` (hoặc lõi thiếu hàm hậu kỳ) → rơi
        # xuống ĐÚNG đường cũ ở dưới, không đụng hàng chờ một tí nào.
        if STATE["batch_max"] > 1:
            key = (voice, (req.get("language") or "vi"),
                   float(req.get("speed") or 0.95),
                   int(req.get("num_step") or 32),
                   float(req.get("guidance") or 2.0))
            job = _Job(text, key)
            STATE["q"].put(job)
            # ≥21/08 (tổng soát bug treo) TRẦN 900s: luồng sinh kẹt cứng trong CUDA (block
            # không ném lỗi) thì trước đây handler chờ VÔ HẠN — client phía tool có trần
            # 600s/câu nên bỏ đi, còn luồng server kẹt mãi. Nay quá trần trả 500 (client
            # coi là câu lỗi, đường xử lý sẵn có).
            if not job.ev.wait(timeout=900.0):
                return self._json(500, {"error": "worker qua 900s khong tra loi (nghi ket GPU) - hay chay lai"})
            if job.err or not job.wav:
                return self._json(500, {"error": job.err or "audio rỗng"})
            data = job.wav
            STATE["last"] = time.time()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        try:
            import soundfile as sf
            with STATE["gen_lock"]:   # model KHÔNG thread-safe → tuần tự hoá sinh audio
                prompt = _get_prompt(voice)
                sr, audio = STATE["eng"].generate(
                    text,
                    language=(req.get("language") or "vi"),
                    speed=float(req.get("speed") or 0.95),
                    num_step=int(req.get("num_step") or 32),
                    guidance_scale=float(req.get("guidance") or 2.0),
                    voice_clone_prompt=prompt,
                    target_lufs=-16.0, trim_silence=True, fade_ms=10.0,
                )
            bio = io.BytesIO()
            sf.write(bio, audio, sr, format="WAV", subtype="PCM_16")
            data = bio.getvalue()
            STATE["last"] = time.time()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:        # noqa: BLE001
            self._json(500, {"error": f"{e}"[:400]})


def _idle_watchdog(srv, timeout: float):
    """Thoát khi rảnh quá lâu → giải phóng VRAM + không để tiến trình GPU mồ côi."""
    if timeout <= 0:
        return
    while True:
        time.sleep(15)
        if time.time() - STATE["last"] > timeout:
            print("[omni] idle-timeout → thoát", flush=True)
            srv.shutdown()
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--asr-dir", default="")
    ap.add_argument("--voices-dir", default="")
    # ★29/07 bỏ Whisper: chỉ đọc giọng LÀM SẴN thì không cần model nhận-diện-lời-thoại
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--idle-timeout", type=float, default=900.0)
    # ★07/08 gộp lô — 1 = TẮT (chạy y hệt bản cũ). Lô 8 KHÔNG tốt hơn lô 4 (câu ngắn bị đệm
    # theo câu dài nhất trong lô) nên mặc định 4.
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--batch-wait-ms", type=float, default=30.0)
    args = ap.parse_args()

    STATE["batch_max"] = max(1, int(args.batch))
    STATE["wait_s"] = max(0.0, float(args.batch_wait_ms) / 1000.0)

    threading.Thread(target=_load_models, args=(args,), daemon=True).start()
    if STATE["batch_max"] > 1:
        threading.Thread(target=_gen_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    threading.Thread(target=_idle_watchdog, args=(srv, args.idle_timeout), daemon=True).start()
    print(f"[omni] serving on 127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
