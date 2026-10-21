"""Offline OCR: only bundled models are permitted; no model downloads."""
from pathlib import Path
from threading import Lock

_lock = Lock()
_engine = None
MODEL_FILES = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
}


def recognize_image(image):
    global _engine
    with _lock:
        import rapidocr
        import onnxruntime
        import numpy as np
        if _engine is None:
            root = Path(rapidocr.__file__).resolve().parent / "models"
            missing = [name for name in MODEL_FILES.values() if not (root / name).is_file()]
            if missing:
                raise RuntimeError("离线识别模型缺失，请重新解压完整软件包：" + ", ".join(missing))
            onnxruntime.disable_telemetry_events()
            params = {f"{key}.model_path": str(root / name) for key, name in MODEL_FILES.items()}
            params.update({"Global.log_level": "error", "Global.text_score": .45,
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "Det.limit_side_len": 1280, "Det.limit_type": "max"})
            _engine = rapidocr.RapidOCR(params=params)
        # RapidOCR's ndarray input is BGR, whereas Pillow is RGB.
        result = _engine(np.asarray(image.convert("RGB"))[:, :, ::-1].copy())
        if result.boxes is None or result.txts is None:
            return []
        return [(box.tolist(), str(text), float(score))
                for box, text, score in zip(result.boxes, result.txts, result.scores)]
