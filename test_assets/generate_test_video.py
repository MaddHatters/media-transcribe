"""Generate a test video with SMPTE color bars, timestamp overlay, and sine tone."""
import subprocess
import sys
from pathlib import Path


def generate(output: Path, duration: int = 60):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"smptebars=size=1920x1080:rate=30:duration={duration},"
        f"drawtext=text='%{{pts\\:hms}}':fontsize=72:fontcolor=white:"
        f"x=(w-tw)/2:y=h-th-50:box=1:boxcolor=black@0.7:boxborderw=10",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(output),
    ]
    subprocess.run(cmd, check=True)
    print(f"Generated: {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    out = Path(__file__).parent / "test_video.mp4"
    generate(out, duration=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
