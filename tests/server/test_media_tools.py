import pytest

from server.services import media_tools


@pytest.mark.parametrize("name", ["ffprobe", "ffmpeg"])
def test_macos_gui_path_falls_back_to_known_install_locations(monkeypatch, name):
    monkeypatch.setattr(media_tools.sys, "platform", "darwin")
    calls = []
    def which(tool, path=None):
        calls.append((tool, path))
        return f"/opt/homebrew/bin/{tool}" if path else None
    monkeypatch.setattr(media_tools.shutil, "which", which)
    assert media_tools.find_media_tool(name) == f"/opt/homebrew/bin/{name}"
    assert calls == [(name, None), (name, "/opt/homebrew/bin:/usr/local/bin")]


def test_explicit_path_tool_takes_precedence(monkeypatch):
    monkeypatch.setattr(media_tools.sys, "platform", "darwin")
    def which(tool, path=None):
        assert path is None
        return "/configured/bin/ffmpeg"
    monkeypatch.setattr(media_tools.shutil, "which", which)
    assert media_tools.find_media_tool("ffmpeg") == "/configured/bin/ffmpeg"


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_other_platforms_do_not_search_macos_directories(monkeypatch, platform):
    monkeypatch.setattr(media_tools.sys, "platform", platform)
    def which(tool, path=None):
        assert path is None
        return None
    monkeypatch.setattr(media_tools.shutil, "which", which)
    assert media_tools.find_media_tool("ffprobe") is None


def test_missing_tools_stay_unavailable(monkeypatch):
    monkeypatch.setattr(media_tools.sys, "platform", "darwin")
    monkeypatch.setattr(media_tools.shutil, "which", lambda *args, **kwargs: None)
    assert media_tools.find_media_tool("ffmpeg") is None


def test_arbitrary_program_lookup_is_rejected():
    with pytest.raises(ValueError):
        media_tools.find_media_tool("sh")


@pytest.mark.asyncio
@pytest.mark.parametrize("available,metadata,frames", [
    (set(), False, False), ({"ffmpeg"}, False, False),
    ({"ffprobe"}, True, False), ({"ffmpeg", "ffprobe"}, True, True),
])
async def test_capability_report_uses_shared_discovery(monkeypatch, available, metadata, frames):
    from server.api import extract
    monkeypatch.setattr(extract, "find_media_tool",
                        lambda name: f"/existing/{name}" if name in available else None)
    result = await extract.input_formats()
    assert result["video_metadata_available"] is metadata
    assert result["video_frames"] is frames
    assert result["video_transcription"] is False
    assert result["video_visual_understanding"] is False
