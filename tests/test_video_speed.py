"""Final export speed uses the same timeline for picture, audio and subtitles."""

import json
import re
import subprocess

import pytest

from purffle_shorts import ffmpeg
from purffle_shorts.cli import build_parser, build_settings
from purffle_shorts.config import ConfigError, Settings
from purffle_shorts.costs import Costs
from purffle_shorts.pipeline import Studio
from purffle_shorts.timing import Word, caption_chunks, srt

from .conftest import needs_ffmpeg


@pytest.mark.parametrize("speed", [0, 0.49, 2.01, -1, float("nan"), float("inf"), "bad"])
def test_invalid_speed_is_rejected(speed):
    with pytest.raises(ConfigError):
        Settings(video_speed=speed)


def test_speed_environment_and_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VIDEO_SPEED", "0.75")
    assert Settings.from_env().video_speed == .75
    args = build_parser().parse_args(["make", "--speed", "1.5"])
    assert build_settings(args).video_speed == 1.5
    args = build_parser().parse_args(["clip", "talk.mp4", "--speed", ".5"])
    assert build_settings(args).video_speed == .5


@pytest.mark.parametrize("speed", [.5, 1, 1.5, 2])
def test_srt_uses_export_timeline(speed):
    chunks = caption_chunks([Word("Hello", 2, 3), Word("world.", 3, 4)], total=5)
    text = srt(chunks, speed=speed)
    first = re.search(r"(\d\d):(\d\d):(\d\d),(\d\d\d)", text)
    seconds = sum(int(n) * scale for n, scale in zip(first.groups(), [3600, 60, 1, .001]))
    assert seconds == pytest.approx(chunks[0].start / speed, abs=.001)
    assert chunks[0].start >= 1  # exporting never mutates the narration timestamps


@needs_ffmpeg
@pytest.mark.parametrize("speed", [.5, 2])
def test_export_duration_audio_captions_and_usage(settings, speed, monkeypatch):
    from purffle_shorts import pipeline as pipeline

    original_srt, original_duration = [], []
    real_srt, real_render = pipeline.srt, pipeline.render_video

    def capture_srt(chunks, **kwargs):
        original_srt.append(real_srt(chunks, **kwargs))
        return original_srt[-1]

    def capture_render(*args):
        original_duration.append(args[4])
        return real_render(*args)

    monkeypatch.setattr(pipeline, "srt", capture_srt)
    monkeypatch.setattr(pipeline, "render_video", capture_render)
    s = settings.with_overrides(offline=True, tts_engine="silent", resolution=(180, 320), fps=24,
                                video_speed=speed, music_volume=0, transition="none")
    studio = Studio(s)
    result = studio.make()
    assert result.ok, result.error
    info = ffmpeg.probe(result.video)
    assert info["duration"] == pytest.approx(original_duration[0] / speed, abs=.12)
    audio = result.folder / "decoded.wav"
    ffmpeg.run(["-i", str(result.video), "-vn", str(audio)])
    assert ffmpeg.duration(audio) == pytest.approx(info["duration"], abs=.12)
    assert (result.folder / "captions.srt").read_text() == original_srt[0]
    assert json.loads((result.folder / "metadata.json").read_text())["video_speed"] == speed
    detail = Costs(studio.history, s).video_details(result.record_id)
    assert detail["duration"] == info["duration"]
    assert detail["units"]["audio_seconds"] == pytest.approx(original_duration[0] - pipeline.END_PAD, abs=.05)


@needs_ffmpeg
def test_clips_apply_speed_after_moment_selection(settings, tmp_path):
    from purffle_shorts.clipper import ClipPlan, render_clip

    source = tmp_path / "talk.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=4",
                    "-f", "lavfi", "-i", "sine=f=220:d=4", "-shortest", str(source)], check=True)
    s = settings.with_overrides(resolution=(180, 320), fps=24, video_speed=2, progress_bar=False)
    folder = tmp_path / "clip"
    folder.mkdir()
    plan = ClipPlan(0, 3, "Clip", "Hook")
    video, chunks, duration = render_clip(s, source, plan, [Word("Hello", .5, 1)], folder)
    assert duration == pytest.approx(1.625)
    assert ffmpeg.duration(video) == pytest.approx(duration, abs=.12)
    assert "00:00:00,250" in srt(chunks, speed=2)
