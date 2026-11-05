"""Helpers for editing downloaded media (images with Pillow-free magic checks, videos with ffmpeg)."""
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

_ffmpeg_cache: Optional[str] = None
_ffmpeg_checked = False


def get_ffmpeg() -> Optional[str]:
    """System ffmpeg if installed (Docker/Render), otherwise the binary bundled by imageio-ffmpeg."""
    global _ffmpeg_cache, _ffmpeg_checked
    if _ffmpeg_checked:
        return _ffmpeg_cache
    _ffmpeg_checked = True
    _ffmpeg_cache = shutil.which("ffmpeg")
    if not _ffmpeg_cache:
        try:
            import imageio_ffmpeg
            _ffmpeg_cache = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _ffmpeg_cache = None
    return _ffmpeg_cache


def sniff_image_ext(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def build_video_filter(rotate: int, flip_h: bool, flip_v: bool, brightness: float, contrast: float, saturation: float) -> str:
    filters: List[str] = []
    if rotate == 90:
        filters.append("transpose=1")
    elif rotate == 180:
        filters.append("transpose=1,transpose=1")
    elif rotate == 270:
        filters.append("transpose=2")
    if flip_h:
        filters.append("hflip")
    if flip_v:
        filters.append("vflip")
    if abs(brightness - 1) > 0.01 or abs(contrast - 1) > 0.01 or abs(saturation - 1) > 0.01:
        # CSS-like multipliers -> ffmpeg eq filter (brightness is additive there)
        filters.append(f"eq=brightness={(brightness - 1) * 0.4:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}")
    # H.264 needs even dimensions
    filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    return ",".join(filters)


def run_ffmpeg_edit(
    src: Path,
    dst: Path,
    start: float,
    duration: Optional[float],
    video_filter: str,
    timeout: int = 600,
) -> Optional[str]:
    """Returns None on success, otherwise an error message."""
    ff = get_ffmpeg()
    if not ff:
        return "Máy chủ chưa có ffmpeg nên chưa chỉnh sửa được video."
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if duration and duration > 0:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += [
        "-vf", video_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "Xử lý video quá lâu, hãy cắt ngắn đoạn video hơn."
    except Exception as e:
        return f"Không chạy được ffmpeg: {e}"
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        return "ffmpeg báo lỗi: " + (proc.stderr or "không rõ")[-300:]
    return None
