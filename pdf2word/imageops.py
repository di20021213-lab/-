"""Подготовка изображений страниц: загрузка, поворот, выравнивание,
удаление цветных печатей и подписей, бинаризация."""

from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
RENDER_DPI = 300

_pdfium_lock = threading.Lock()  # PDFium не потокобезопасен


@dataclass
class SourcePage:
    index: int
    width_pt: float      # размер страницы в пунктах (как в исходном документе)
    height_pt: float
    dpi: float           # разрешение, в котором отрисовано изображение


class PageSource:
    """Отдаёт страницы PDF или картинок как numpy-изображения (BGR)."""

    def __init__(self, path: str, dpi: int = RENDER_DPI):
        self.path = path
        self.dpi = dpi
        ext = os.path.splitext(path)[1].lower()
        self.kind = "image" if ext in IMAGE_EXT else "pdf"
        self._pdf = None
        self._frames: list[Image.Image] = []
        if self.kind == "pdf":
            import pypdfium2 as pdfium
            with _pdfium_lock:
                try:
                    self._pdf = pdfium.PdfDocument(path)
                except pdfium.PdfiumError as exc:
                    raise ValueError(f"Не удалось открыть PDF: {exc}") from exc
                self.count = len(self._pdf)
        else:
            img = Image.open(path)
            n = getattr(img, "n_frames", 1)
            for i in range(n):
                img.seek(i)
                self._frames.append(img.copy())
            self.count = len(self._frames)

    def close(self):
        if self._pdf is not None:
            with _pdfium_lock:
                self._pdf.close()
            self._pdf = None

    def render(self, index: int) -> tuple[np.ndarray, SourcePage]:
        if self.kind == "pdf":
            with _pdfium_lock:
                page = self._pdf[index]
                w_pt, h_pt = page.get_size()
                scale = self.dpi / 72.0
                # огромные листы (чертежи) ограничиваем по длинной стороне
                longest = max(w_pt, h_pt) * scale
                if longest > 7000:
                    scale *= 7000 / longest
                bitmap = page.render(scale=scale, rotation=0)
                pil = bitmap.to_pil().convert("RGB")
                page.close()
            arr = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
            return arr, SourcePage(index, w_pt, h_pt, scale * 72.0)
        frame = self._frames[index]
        dpi = frame.info.get("dpi", (0, 0))[0] or 0
        rgb = frame.convert("RGB")
        w, h = rgb.size
        if not dpi or dpi < 50:
            # нет сведений о разрешении: считаем, что это лист A4
            dpi = max(w, h) / 11.69
        arr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        w_pt, h_pt = w / dpi * 72.0, h / dpi * 72.0
        out_dpi = float(dpi)
        if abs(dpi - self.dpi) > 5 and max(w, h) * self.dpi / dpi <= 7000:
            factor = self.dpi / dpi
            interp = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
            arr = cv2.resize(arr, None, fx=factor, fy=factor, interpolation=interp)
            out_dpi = float(self.dpi)
        return arr, SourcePage(index, w_pt, h_pt, out_dpi)


# --------------------------------------------------------------------------
# Цвет, фон, бинаризация

def remove_color_ink(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """Стирает синие/фиолетовые пиксели (печати, подписи).

    Тёмные пиксели не трогаем: там, где печать легла на чёрный текст,
    буквы остаются. Возвращает (изображение, маска стёртого или None)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    hue = (h >= 95) & (h <= 165)
    b = bgr[..., 0].astype(np.int16)
    g = bgr[..., 1].astype(np.int16)
    r = bgr[..., 2].astype(np.int16)
    strong = hue & (s >= 50) & (v >= 100) & (b - np.maximum(r, g) >= 20)
    if strong.mean() < 0.00005:
        return bgr, None
    light = hue & (s >= 22) & (v >= 150)
    removed = strong | light
    out = bgr.copy()
    out[removed] = 255
    return out, strong.astype(np.uint8) * 255


def to_gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr


def flatten_background(gray: np.ndarray) -> np.ndarray:
    """Выравнивает неравномерный фон (тени, желтизна бумаги)."""
    h, w = gray.shape
    small = cv2.resize(gray, (max(1, w // 8), max(1, h // 8)), interpolation=cv2.INTER_AREA)
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    bg = cv2.medianBlur(bg, 5)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    bg = np.maximum(bg, 1).astype(np.float32)
    norm = gray.astype(np.float32) / bg * 255.0
    return np.clip(norm, 0, 255).astype(np.uint8)


def binarize(gray: np.ndarray) -> np.ndarray:
    """Маска чернил: 255 — краска, 0 — фон."""
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # отсекаем светлый шум: пиксель должен быть заметно темнее фона
    otsu[gray > 200] = 0
    return otsu


# --------------------------------------------------------------------------
# Ориентация и наклон

def rotate90(img: np.ndarray, clockwise_deg: int) -> np.ndarray:
    k = (clockwise_deg // 90) % 4
    if k == 0:
        return img
    codes = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180,
             3: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(img, codes[k])


def text_is_vertical(ink: np.ndarray) -> bool | None:
    """Грубая проверка: строки текста идут вертикально?

    У горизонтального текста проекция на вертикальную ось «полосатая»
    (строки и межстрочные промежутки), у повёрнутого — наоборот."""
    small = cv2.resize(ink, (max(1, ink.shape[1] // 4), max(1, ink.shape[0] // 4)),
                       interpolation=cv2.INTER_AREA)
    if small.mean() < 0.5:
        return None
    rows = small.mean(axis=1)
    cols = small.mean(axis=0)
    rv = np.var(rows) / max(1e-6, rows.mean() ** 2)
    cv = np.var(cols) / max(1e-6, cols.mean() ** 2)
    if max(rv, cv) < 1e-3:
        return None
    return cv > rv * 1.6


def estimate_skew(ink: np.ndarray, max_angle: float = 5.0) -> float:
    """Угол наклона текста (в градусах) методом проекций."""
    h, w = ink.shape
    scale = 1200.0 / max(h, w)
    small = cv2.resize(ink, (max(1, int(w * scale)), max(1, int(h * scale))),
                       interpolation=cv2.INTER_AREA)
    if small.mean() < 0.3:
        return 0.0
    sh, sw = small.shape
    center = (sw / 2, sh / 2)

    def score(angle):
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rot = cv2.warpAffine(small, m, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)
        prof = rot.sum(axis=1, dtype=np.float64)
        d = np.diff(prof)
        return float((d * d).sum())

    best, best_s = 0.0, score(0.0)
    for a in np.arange(-max_angle, max_angle + 1e-6, 0.25):
        s = score(float(a))
        if s > best_s:
            best, best_s = float(a), s
    for a in np.arange(best - 0.25, best + 0.25 + 1e-6, 0.05):
        s = score(float(a))
        if s > best_s:
            best, best_s = float(a), s
    return best


def rotate_small(img: np.ndarray, angle: float, border_value: int = 255) -> np.ndarray:
    if abs(angle) < 0.04:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    border = (border_value,) * 3 if img.ndim == 3 else border_value
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def png_bytes(img: np.ndarray, dpi: int) -> bytes:
    pil = Image.fromarray(img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil.save(buf, format="PNG", dpi=(dpi, dpi), compress_level=1)
    return buf.getvalue()


def tiff_stack(images: list[np.ndarray], dpi: int) -> bytes:
    pils = [Image.fromarray(im) for im in images]
    buf = io.BytesIO()
    pils[0].save(buf, format="TIFF", save_all=True, append_images=pils[1:],
                 dpi=(dpi, dpi), compression="tiff_lzw")
    return buf.getvalue()


def estimate_xheight(ink: np.ndarray) -> float:
    """Типичная высота строчных букв по связным компонентам."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n < 20:
        return 20.0
    hs = stats[1:, cv2.CC_STAT_HEIGHT]
    ws = stats[1:, cv2.CC_STAT_WIDTH]
    areas = stats[1:, cv2.CC_STAT_AREA]
    ok = (hs >= 6) & (hs <= 120) & (ws >= 3) & (ws <= 150) & (areas >= 12)
    if ok.sum() < 20:
        return 20.0
    hs = hs[ok]
    # самая частая высота — строчные буквы без выносных элементов
    hist = np.bincount(hs)
    mode = int(np.argmax(np.convolve(hist, np.ones(3), mode="same")))
    return float(max(8, mode))
