"""
文档解析：PDF 文字/表格抽取 + 图片/扫描件视觉识别。

策略：
1) PDF → pdfplumber 抽文本与表格
2) 若文本过少（扫描件）或输入为图片 → 通义视觉模型 qwen-vl-plus 识别
3) 无 Key / 失败时返回已抽到的文本表格（降级）
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}


def _table_to_markdown(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    clean = [[("" if c is None else str(c).strip()) for c in row] for row in rows]
    clean = [r for r in clean if any(r)]
    if not clean:
        return ""
    width = max(len(r) for r in clean)
    for r in clean:
        while len(r) < width:
            r.append("")
    header = clean[0]
    body = clean[1:] if len(clean) > 1 else []
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _extract_pdf_with_pdfplumber(path: Path, max_pages: int = 20) -> dict[str, Any]:
    import pdfplumber

    pages_text: list[str] = []
    tables: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            text = (page.extract_text() or "").strip()
            if text:
                pages_text.append(f"## 第 {i + 1} 页\n{text}")
            try:
                raw_tables = page.extract_tables() or []
            except Exception:
                raw_tables = []
            for ti, tbl in enumerate(raw_tables):
                md = _table_to_markdown(tbl or [])
                if md:
                    tables.append(
                        {
                            "page": i + 1,
                            "index": ti + 1,
                            "markdown": md,
                            "rows": tbl,
                        }
                    )
    full_text = "\n\n".join(pages_text).strip()
    return {
        "engine": "pdfplumber",
        "page_count_read": min(max_pages, len(pages_text) + len(tables)),
        "text": full_text,
        "tables": tables,
        "char_count": len(full_text),
    }


def _pdf_pages_to_png_b64(path: Path, max_pages: int = 3, dpi: int = 144) -> list[str]:
    """扫描件兜底：把前几页渲成图给视觉模型。"""
    import fitz  # pymupdf

    out: list[str] = []
    doc = fitz.open(str(path))
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i in range(min(max_pages, doc.page_count)):
            pix = doc.load_page(i).get_pixmap(matrix=mat, alpha=False)
            out.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    finally:
        doc.close()
    return out


def _image_file_to_b64(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(ext, "image/png")


def _vision_recognize(images_b64: list[str], mime: str = "image/png", hint: str = "") -> dict[str, Any]:
    settings = get_settings()
    if not settings.use_real_llm:
        return {
            "engine": "vision-mock",
            "text": "（演示模式：未调用视觉模型）请配置 API Key 后识别扫描件/图片。",
            "tables_markdown": [],
            "structured": {},
        }

    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    model = settings.resolved_vision_model
    llm = ChatOpenAI(
        model=model,
        api_key=settings.resolved_api_key,
        base_url=settings.llm_base_url.rstrip("/"),
        temperature=0,
        max_tokens=4096,
    )
    from backend.agents.prompts_registry import DOC_VISION_PROMPT

    prompt = DOC_VISION_PROMPT.format(hint=hint or "无")
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64 in images_b64[:4]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )
    resp = llm.invoke([HumanMessage(content=content)])
    raw = (getattr(resp, "content", None) or str(resp)).strip()
    structured = {}
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            structured = json.loads(m.group(1))
        except json.JSONDecodeError:
            structured = {}
    # 粗提 markdown 表
    tables_md = re.findall(r"(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)*)", raw)
    return {
        "engine": f"vision:{model}",
        "text": raw,
        "tables_markdown": tables_md,
        "structured": structured,
    }


def parse_document_file(
    path: str | Path,
    *,
    hint: str = "",
    force_vision: bool = False,
    min_text_chars: int = 80,
) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    ext = path.suffix.lower()
    result: dict[str, Any] = {
        "filename": path.name,
        "ext": ext,
        "text": "",
        "tables": [],
        "structured": {},
        "engines": [],
        "summary": "",
    }

    if ext in PDF_EXTS:
        try:
            extracted = _extract_pdf_with_pdfplumber(path)
            result["text"] = extracted.get("text") or ""
            result["tables"] = extracted.get("tables") or []
            result["engines"].append("pdfplumber")
            result["char_count"] = extracted.get("char_count", 0)
        except Exception as e:
            logger.error(f"doc.pdfplumber_failed err={e}")
            result["engines"].append(f"pdfplumber_error:{e}")

        need_vision = force_vision or (result.get("char_count", 0) < min_text_chars and not result["tables"])
        if need_vision:
            try:
                imgs = _pdf_pages_to_png_b64(path, max_pages=3)
                if imgs:
                    vis = _vision_recognize(imgs, mime="image/png", hint=hint)
                    result["engines"].append(vis.get("engine") or "vision")
                    # 合并：视觉结果补到文本后
                    if vis.get("text"):
                        result["text"] = (result["text"] + "\n\n--- 视觉识别 ---\n" + vis["text"]).strip()
                    if vis.get("structured"):
                        result["structured"] = vis["structured"]
                    for i, md in enumerate(vis.get("tables_markdown") or []):
                        result["tables"].append({"page": 0, "index": i + 1, "markdown": md, "source": "vision"})
            except Exception as e:
                logger.error(f"doc.vision_pdf_failed err={e}")
                result["engines"].append(f"vision_error:{e}")

    elif ext in IMAGE_EXTS:
        try:
            b64 = _image_file_to_b64(path)
            vis = _vision_recognize([b64], mime=_guess_mime(path), hint=hint)
            result["engines"].append(vis.get("engine") or "vision")
            result["text"] = vis.get("text") or ""
            result["structured"] = vis.get("structured") or {}
            for i, md in enumerate(vis.get("tables_markdown") or []):
                result["tables"].append({"page": 1, "index": i + 1, "markdown": md, "source": "vision"})
        except Exception as e:
            logger.error(f"doc.vision_image_failed err={e}")
            result["engines"].append(f"vision_error:{e}")
            result["text"] = f"图片识别失败：{e}"
    else:
        raise ValueError(f"暂不支持的文件类型: {ext}（支持 PDF / PNG / JPG / WEBP）")

    n_tables = len(result["tables"])
    n_chars = len(result.get("text") or "")
    result["summary"] = (
        f"已解析 {path.name}：约 {n_chars} 字，表格 {n_tables} 个；引擎={'+'.join(result['engines']) or '无'}"
    )
    return result


def save_upload_bytes(data: bytes, filename: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\u4e00-\u9fff\-]+", "_", filename or "upload.bin")
    path = dest_dir / safe
    # 避免覆盖
    if path.exists():
        stem, suf = path.stem, path.suffix
        i = 1
        while True:
            cand = dest_dir / f"{stem}_{i}{suf}"
            if not cand.exists():
                path = cand
                break
            i += 1
    path.write_bytes(data)
    return path
