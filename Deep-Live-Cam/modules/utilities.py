import glob
import hashlib
import mimetypes
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Any
from tqdm import tqdm

import modules.globals

TEMP_FILE = "temp.mp4"
TEMP_DIRECTORY = "temp"
MAX_MODEL_DOWNLOAD_BYTES = 1024 * 1024 * 1024

MODEL_SHA256: Dict[str, str] = {
    "https://huggingface.co/hacksider/deep-live-cam/resolve/main/inswapper_128.onnx": "e4a3f08c753cb72d04e10aa0f7dbe3deebbf39567d4ead6dce08e98aa49e16af",
}


def run_ffmpeg(args: List[str]) -> bool:
    """Run ffmpeg with hardware acceleration and optimized settings."""
    commands = [
        "ffmpeg",
        "-hide_banner",
        "-hwaccel", "auto",  # Auto-detect hardware acceleration
        "-hwaccel_output_format", "auto",  # Use hardware format when possible
        "-threads", str(modules.globals.execution_threads or 0),  # 0 = auto-detect optimal thread count
        "-loglevel", modules.globals.log_level,
    ]
    commands.extend(args)
    try:
        subprocess.check_output(commands, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError as error:
        output = error.output.decode(errors="ignore").strip()
        if output:
            print(output)
    except Exception as error:
        print(f"ffmpeg execution failed: {error}")
    return False


def detect_fps(target_path: str) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        target_path,
    ]
    output = subprocess.check_output(command).decode().strip().split("/")
    try:
        numerator, denominator = map(int, output)
        return numerator / denominator
    except Exception:
        pass
    return 30.0


def extract_frames(target_path: str) -> None:
    """Extract frames with hardware acceleration and optimized settings."""
    temp_directory_path = get_temp_directory_path(target_path)

    # Write a contiguous image sequence so the later "%04d.png" input pattern
    # used during encoding can consume every frame reliably.
    run_ffmpeg(
        [
            "-i", target_path,
            "-vf", "format=rgb24",  # Use video filter for format conversion (faster)
            "-vsync", "0",  # Prevent frame duplication
            os.path.join(temp_directory_path, "%04d.png"),
        ]
    )


def create_video(target_path: str, fps: float = 30.0) -> bool:
    """Create video with hardware-accelerated encoding and optimized settings."""
    temp_output_path = get_temp_output_path(target_path)
    temp_directory_path = get_temp_directory_path(target_path)

    # Determine optimal encoder based on available hardware
    encoder = modules.globals.video_encoder
    encoder_options = []

    # GPU-accelerated encoding options
    if 'CUDAExecutionProvider' in modules.globals.execution_providers:
        # NVIDIA GPU encoding
        if encoder == 'libx264':
            encoder = 'h264_nvenc'
            encoder_options = [
                "-preset", "p7",  # Highest quality preset for NVENC
                "-tune", "hq",  # High quality tuning
                "-rc", "vbr",  # Variable bitrate
                "-cq", str(modules.globals.video_quality),  # Quality level
                "-b:v", "0",  # Let CQ control bitrate
                "-multipass", "fullres",  # Two-pass encoding for better quality
            ]
        elif encoder == 'libx265':
            encoder = 'hevc_nvenc'
            encoder_options = [
                "-preset", "p7",
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", str(modules.globals.video_quality),
                "-b:v", "0",
            ]
    elif 'DmlExecutionProvider' in modules.globals.execution_providers:
        # AMD/Intel GPU encoding (DirectML on Windows)
        if encoder == 'libx264':
            # Try AMD AMF encoder
            encoder = 'h264_amf'
            encoder_options = [
                "-quality", "quality",  # Quality mode
                "-rc", "vbr_latency",
                "-qp_i", str(modules.globals.video_quality),
                "-qp_p", str(modules.globals.video_quality),
            ]
        elif encoder == 'libx265':
            encoder = 'hevc_amf'
            encoder_options = [
                "-quality", "quality",
                "-rc", "vbr_latency",
                "-qp_i", str(modules.globals.video_quality),
                "-qp_p", str(modules.globals.video_quality),
            ]
    else:
        # CPU encoding with optimized settings
        if encoder == 'libx264':
            encoder_options = [
                "-preset", "medium",  # Balance speed/quality
                "-crf", str(modules.globals.video_quality),
                "-tune", "film",  # Optimize for film content
            ]
        elif encoder == 'libx265':
            encoder_options = [
                "-preset", "medium",
                "-crf", str(modules.globals.video_quality),
                "-x265-params", "log-level=error",
            ]
        elif encoder == 'libvpx-vp9':
            encoder_options = [
                "-crf", str(modules.globals.video_quality),
                "-b:v", "0",  # Constant quality mode
                "-cpu-used", "2",  # Speed vs quality (0-5, lower=slower/better)
            ]

    # Build ffmpeg command
    ffmpeg_args = [
        "-r", str(fps),
        "-i", os.path.join(temp_directory_path, "%04d.png"),
        "-c:v", encoder,
    ]

    # Add encoder-specific options
    ffmpeg_args.extend(encoder_options)

    # Add common options
    ffmpeg_args.extend([
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",  # Enable fast start for web playback
        "-vf", "colorspace=bt709:iall=bt601-6-625:fast=1",
        "-y",
        temp_output_path,
    ])

    # Try with hardware encoder first, fallback to software if it fails
    success = run_ffmpeg(ffmpeg_args)

    if not success and encoder in ['h264_nvenc', 'hevc_nvenc', 'h264_amf', 'hevc_amf']:
        # Fallback to software encoding
        print(f"Hardware encoding with {encoder} failed, falling back to software encoding...")
        fallback_encoder = 'libx264' if 'h264' in encoder else 'libx265'
        ffmpeg_args_fallback = [
            "-r", str(fps),
            "-i", os.path.join(temp_directory_path, "%04d.png"),
            "-c:v", fallback_encoder,
            "-preset", "medium",
            "-crf", str(modules.globals.video_quality),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-vf", "colorspace=bt709:iall=bt601-6-625:fast=1",
            "-y",
            temp_output_path,
        ]
        success = run_ffmpeg(ffmpeg_args_fallback)
    return success and os.path.isfile(temp_output_path)


def restore_audio(target_path: str, output_path: str) -> None:
    temp_output_path = get_temp_output_path(target_path)
    done = run_ffmpeg(
        [
            "-i",
            temp_output_path,
            "-i",
            target_path,
            "-c:v",
            "copy",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-y",
            output_path,
        ]
    )
    if not done:
        move_temp(target_path, output_path)


def get_temp_frame_paths(target_path: str) -> List[str]:
    temp_directory_path = get_temp_directory_path(target_path)
    return glob.glob((os.path.join(glob.escape(temp_directory_path), "*.png")))


def get_temp_directory_path(target_path: str) -> str:
    target_name, _ = os.path.splitext(os.path.basename(target_path))
    target_directory_path = os.path.dirname(target_path)
    return os.path.join(target_directory_path, TEMP_DIRECTORY, target_name)


def get_temp_output_path(target_path: str) -> str:
    temp_directory_path = get_temp_directory_path(target_path)
    return os.path.join(temp_directory_path, TEMP_FILE)


def normalize_output_path(source_path: str, target_path: str, output_path: str) -> Any:
    if source_path and target_path:
        source_name, _ = os.path.splitext(os.path.basename(source_path))
        target_name, target_extension = os.path.splitext(os.path.basename(target_path))
        if os.path.isdir(output_path):
            return os.path.join(
                output_path, source_name + "-" + target_name + target_extension
            )
    return output_path


def create_temp(target_path: str) -> None:
    temp_directory_path = get_temp_directory_path(target_path)
    temp_directory = Path(temp_directory_path)
    if temp_directory.is_symlink():
        raise ValueError(f"Refusing to use symlinked temporary directory: {temp_directory}")
    temp_directory.mkdir(parents=True, exist_ok=True)
    assert_safe_temp_output_path(target_path)


def assert_safe_temp_output_path(target_path: str) -> None:
    temp_output_path = Path(get_temp_output_path(target_path))
    if temp_output_path.is_symlink():
        raise ValueError(f"Refusing to use symlinked temporary output: {temp_output_path}")
    if temp_output_path.exists() and not temp_output_path.is_file():
        raise ValueError(f"Refusing to use non-file temporary output: {temp_output_path}")


def move_temp(target_path: str, output_path: str) -> None:
    temp_output_path = get_temp_output_path(target_path)
    if os.path.isfile(temp_output_path):
        if os.path.isfile(output_path):
            os.remove(output_path)
        shutil.move(temp_output_path, output_path)


def clean_temp(target_path: str) -> None:
    temp_directory_path = get_temp_directory_path(target_path)
    parent_directory_path = os.path.dirname(temp_directory_path)
    if not modules.globals.keep_frames and os.path.isdir(temp_directory_path):
        shutil.rmtree(temp_directory_path)
    if os.path.exists(parent_directory_path) and not os.listdir(parent_directory_path):
        os.rmdir(parent_directory_path)


def has_image_extension(image_path: str) -> bool:
    return image_path.lower().endswith(("png", "jpg", "jpeg"))


def is_image(image_path: str) -> bool:
    if image_path and os.path.isfile(image_path):
        mimetype, _ = mimetypes.guess_type(image_path)
        return bool(mimetype and mimetype.startswith("image/"))
    return False


def is_video(video_path: str) -> bool:
    if video_path and os.path.isfile(video_path):
        mimetype, _ = mimetypes.guess_type(video_path)
        return bool(mimetype and mimetype.startswith("video/"))
    return False


def verify_file_sha256(file_path: str, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 verification failed for {file_path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


def _download_basename(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return os.path.basename(parsed.path)


def _expected_sha256_for_url(
    url: str,
    expected_sha256: Dict[str, str] | None,
) -> str:
    if expected_sha256 and url in expected_sha256:
        return expected_sha256[url]
    if url in MODEL_SHA256:
        return MODEL_SHA256[url]
    raise ValueError(f"No SHA-256 pin configured for model download: {url}")


def conditional_download(
    download_directory_path: str,
    urls: List[str],
    expected_sha256: Dict[str, str] | None = None,
    max_bytes: int = MAX_MODEL_DOWNLOAD_BYTES,
) -> None:
    if not os.path.exists(download_directory_path):
        os.makedirs(download_directory_path)
    for url in urls:
        download_file_path = os.path.join(
            download_directory_path, _download_basename(url)
        )
        expected_hash = _expected_sha256_for_url(url, expected_sha256)
        if os.path.exists(download_file_path):
            verify_file_sha256(download_file_path, expected_hash)
            continue

        request = urllib.request.Request(url)
        tmp_file_path = f"{download_file_path}.download"
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                total = int(response.headers.get("Content-Length", 0))
                if total > max_bytes:
                    raise ValueError(f"Download exceeds {max_bytes} byte limit: {url}")
                downloaded = 0
                with tqdm(
                    total=total,
                    desc="Downloading",
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress:
                    with open(tmp_file_path, "wb") as f:
                        while True:
                            buffer = response.read(8192)
                            if not buffer:
                                break
                            downloaded += len(buffer)
                            if downloaded > max_bytes:
                                raise ValueError(
                                    f"Download exceeds {max_bytes} byte limit: {url}"
                                )
                            f.write(buffer)
                            progress.update(len(buffer))
            verify_file_sha256(tmp_file_path, expected_hash)
            os.replace(tmp_file_path, download_file_path)
        except Exception:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            raise


def resolve_relative_path(path: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), path))


def get_video_dimensions(target_path: str) -> tuple:
    """Get video width and height using ffprobe."""
    command = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        target_path,
    ]
    output = subprocess.check_output(command).decode().strip()
    width, height = map(int, output.split("x"))
    return width, height


def estimate_frame_count(target_path: str, fps: float = None) -> int:
    """Estimate total frame count from video duration and fps."""
    if fps is None:
        fps = detect_fps(target_path)
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        target_path,
    ]
    try:
        output = subprocess.check_output(command).decode().strip()
        duration = float(output)
        return int(duration * fps)
    except Exception:
        return 0
