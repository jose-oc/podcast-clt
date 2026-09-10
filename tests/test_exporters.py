"""Unit tests for transcript exporters and export manager."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from podcast_ctl.exporters import (
    BaseExporter,
    ExportManager,
    JsonExporter,
    MarkdownExporter,
    ProseExporter,
    SrtExporter,
    VttExporter,
    format_duration,
    format_timestamp,
    normalize_sentence_text,
    slugify,
)
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment


@pytest.fixture
def sample_metadata() -> EpisodeMetadata:
    return EpisodeMetadata(
        show_title="The AI Revolution",
        episode_title="Episode 42: Next-Gen Autonomous Agents!",
        episode_id="ep-42-agents",
        show_id="ai-rev",
        audio_url="https://example.com/audio/ep42.mp3",
        duration_seconds=2712.5,
        published_date="2026-09-08T12:00:00Z",
        source_type="rss",
    )


@pytest.fixture
def sample_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            start=0.0,
            end=3.5,
            text="Welcome to the show, everyone.",
            speaker="Host",
        ),
        TranscriptSegment(
            start=4.0,
            end=7.2,
            text="Today we are discussing autonomous AI agents.",
            speaker="Host",
        ),
        # Speaker change and pause > 3s
        TranscriptSegment(
            start=12.0,
            end=16.0,
            text="Thanks for having me on the show.",
            speaker="Guest",
        ),
        TranscriptSegment(
            start=16.5,
            end=21.0,
            text="Agents are evolving rapidly this year.",
            speaker="Guest",
        ),
        # Same speaker, but big pause (21.0 to 26.0 is 5.0s > 3s)
        TranscriptSegment(
            start=26.0,
            end=30.0,
            text="We are seeing massive breakthroughs in multi-agent orchestration.",
            speaker="Guest",
        ),
    ]


@pytest.fixture
def sample_result(sample_metadata: EpisodeMetadata, sample_segments: list[TranscriptSegment]) -> TranscriptResult:
    return TranscriptResult(
        metadata=sample_metadata,
        segments=sample_segments,
        tier_used="whisper",
    )


# =============================================================================
# Helper Utilities Tests
# =============================================================================


def test_format_timestamp() -> None:
    # Standard formats
    assert format_timestamp(0.0) == "00:00:00"
    assert format_timestamp(65.0) == "00:01:05"
    assert format_timestamp(3665.0) == "01:01:05"

    # Without hours when hours == 0
    assert format_timestamp(65.0, always_include_hours=False) == "01:05"
    assert format_timestamp(3665.0, always_include_hours=False) == "01:01:05"

    # Decimal separators (SRT vs VTT)
    assert format_timestamp(1.5, decimal_separator=",") == "00:00:01,500"
    assert format_timestamp(1.5, decimal_separator=".") == "00:00:01.500"
    assert format_timestamp(3661.1234, decimal_separator=".", decimal_places=2) == "01:01:01.12"

    # Edge cases: negative numbers
    assert format_timestamp(-10.0) == "00:00:00"


def test_format_duration() -> None:
    assert format_duration(None) == "00:00:00"
    assert format_duration(-5.0) == "00:00:00"
    assert format_duration(2712.0) == "00:45:12"


def test_slugify() -> None:
    assert slugify("The Daily: Why AI Matters (Ep. 42!)") == "the-daily-why-ai-matters-ep-42"
    assert slugify("Café & Résumé") == "cafe-resume"
    assert slugify("   Lots   of    Spaces   ") == "lots-of-spaces"
    assert slugify("???!!!") == "untitled"
    assert slugify("", fallback="default-show") == "default-show"


def test_normalize_sentence_text() -> None:
    # Whitespace cleanup
    assert normalize_sentence_text("   hello   world   ") == "Hello world"

    # Punctuation spacing fixes
    assert normalize_sentence_text("hello , world .") == "Hello, world."
    assert normalize_sentence_text("hello.world") == "Hello. World"
    assert normalize_sentence_text("first sentence. second sentence! third? yes.") == (
        "First sentence. Second sentence! Third? Yes."
    )

    # Empty string
    assert normalize_sentence_text("") == ""
    assert normalize_sentence_text("   ") == ""


# =============================================================================
# Markdown Exporter Tests
# =============================================================================


def test_markdown_exporter_frontmatter_and_content(sample_result: TranscriptResult) -> None:
    exporter = MarkdownExporter()
    output = exporter.export(sample_result)

    assert output.startswith("---\n")
    parts = output.split("---\n", 2)
    assert len(parts) >= 3

    frontmatter_yaml = parts[1]
    parsed_meta = yaml.safe_load(frontmatter_yaml)

    assert parsed_meta["title"] == "Episode 42: Next-Gen Autonomous Agents!"
    assert parsed_meta["show"] == "The AI Revolution"
    assert parsed_meta["duration"] == "00:45:12"
    assert parsed_meta["published"] == "2026-09-08T12:00:00Z"
    assert parsed_meta["tier"] == "whisper"

    # Heading check
    assert "# Episode 42: Next-Gen Autonomous Agents!" in output

    # Timestamped blocks with speakers check
    assert "**[00:00:00]** Host: Welcome to the show, everyone. Today we are discussing autonomous AI agents." in output
    assert "**[00:00:12]** Guest: Thanks for having me on the show. Agents are evolving rapidly this year." in output
    assert "**[00:00:26]** Guest: We are seeing massive breakthroughs in multi-agent orchestration." in output


def test_markdown_exporter_without_speakers(sample_metadata: EpisodeMetadata) -> None:
    segments = [
        TranscriptSegment(start=0.0, end=3.0, text="Hello world."),
        TranscriptSegment(start=3.2, end=6.0, text="Welcome to the podcast."),
        TranscriptSegment(start=15.0, end=18.0, text="Moving to chapter two."),
    ]
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=segments,
        tier_used="rss",
    )
    exporter = MarkdownExporter()
    output = exporter.export(result)

    assert "**[00:00:00]** Hello world. Welcome to the podcast." in output
    assert "**[00:00:15]** Moving to chapter two." in output


def test_markdown_exporter_empty_segments(sample_metadata: EpisodeMetadata) -> None:
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=[],
        tier_used="cloud",
        raw_text="This is a raw text transcript without segment timestamps.",
    )
    exporter = MarkdownExporter()
    output = exporter.export(result)

    frontmatter_yaml = output.split("---\n", 2)[1]
    parsed_meta = yaml.safe_load(frontmatter_yaml)
    assert parsed_meta["title"] == "Episode 42: Next-Gen Autonomous Agents!"
    assert "# Episode 42: Next-Gen Autonomous Agents!" in output
    assert "This is a raw text transcript without segment timestamps." in output


# =============================================================================
# Prose Exporter Tests
# =============================================================================


def test_prose_exporter_grouping_and_smoothing(sample_result: TranscriptResult) -> None:
    exporter = ProseExporter()
    output = exporter.export(sample_result)

    paragraphs = output.strip().split("\n\n")
    assert len(paragraphs) == 3

    assert paragraphs[0] == "Host: Welcome to the show, everyone. Today we are discussing autonomous AI agents."
    assert paragraphs[1] == "Guest: Thanks for having me on the show. Agents are evolving rapidly this year."
    assert paragraphs[2] == "Guest: We are seeing massive breakthroughs in multi-agent orchestration."


def test_prose_exporter_without_speaker_labels(sample_result: TranscriptResult) -> None:
    exporter = ProseExporter(include_speakers=False)
    output = exporter.export(sample_result)

    paragraphs = output.strip().split("\n\n")
    assert len(paragraphs) == 3

    assert paragraphs[0] == "Welcome to the show, everyone. Today we are discussing autonomous AI agents."
    assert paragraphs[1] == "Thanks for having me on the show. Agents are evolving rapidly this year."
    assert paragraphs[2] == "We are seeing massive breakthroughs in multi-agent orchestration."


def test_prose_exporter_raw_text_fallback(sample_metadata: EpisodeMetadata) -> None:
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=[],
        tier_used="cloud",
        raw_text="hello world. this is paragraph one .\n\nand here is paragraph two .",
    )
    exporter = ProseExporter()
    output = exporter.export(result)

    assert output == "Hello world. This is paragraph one.\n\nAnd here is paragraph two.\n"


def test_prose_exporter_empty_result(sample_metadata: EpisodeMetadata) -> None:
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=[],
        tier_used="cloud",
        raw_text="",
    )
    exporter = ProseExporter()
    assert exporter.export(result) == ""


# =============================================================================
# Subtitle Exporters Tests (SRT & VTT)
# =============================================================================


def test_srt_exporter_compliance(sample_result: TranscriptResult) -> None:
    exporter = SrtExporter()
    output = exporter.export(sample_result)

    assert output.startswith("1\n00:00:00,000 --> 00:00:03,500\nHost: Welcome to the show, everyone.\n\n")
    assert "\n2\n00:00:04,000 --> 00:00:07,200\nHost: Today we are discussing autonomous AI agents.\n\n" in output
    assert "\n3\n00:00:12,000 --> 00:00:16,000\nGuest: Thanks for having me on the show.\n\n" in output
    assert "\n4\n00:00:16,500 --> 00:00:21,000\nGuest: Agents are evolving rapidly this year.\n\n" in output
    assert "\n5\n00:00:26,000 --> 00:00:30,000\nGuest: We are seeing massive breakthroughs in multi-agent orchestration.\n\n" in output

    # Check comma separator compliance
    assert "," in output.split(" --> ")[0]
    assert "." not in output.split(" --> ")[0].split("\n")[-1]


def test_vtt_exporter_compliance(sample_result: TranscriptResult) -> None:
    exporter = VttExporter()
    output = exporter.export(sample_result)

    assert output.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:03.500\nHost: Welcome to the show, everyone.\n\n")
    assert "\n00:00:04.000 --> 00:00:07.200\nHost: Today we are discussing autonomous AI agents.\n\n" in output
    assert "\n00:00:12.000 --> 00:00:16.000\nGuest: Thanks for having me on the show.\n\n" in output

    # Check period separator compliance
    first_cue = output.split("\n\n")[1]
    assert "." in first_cue.split(" --> ")[0]
    assert "," not in first_cue.split(" --> ")[0]


def test_subtitles_without_speakers(sample_metadata: EpisodeMetadata) -> None:
    segments = [
        TranscriptSegment(start=1.0, end=4.5, text="First subtitle."),
        TranscriptSegment(start=5.0, end=8.0, text="Second subtitle."),
    ]
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=segments,
        tier_used="whisper",
    )

    srt_out = SrtExporter().export(result)
    assert "1\n00:00:01,000 --> 00:00:04,500\nFirst subtitle.\n\n" in srt_out
    assert "2\n00:00:05,000 --> 00:00:08,000\nSecond subtitle.\n\n" in srt_out

    vtt_out = VttExporter().export(result)
    assert "WEBVTT\n\n00:00:01.000 --> 00:00:04.500\nFirst subtitle.\n\n" in vtt_out
    assert "00:00:05.000 --> 00:00:08.000\nSecond subtitle.\n\n" in vtt_out


def test_subtitles_empty_segments_fallback(sample_metadata: EpisodeMetadata) -> None:
    result = TranscriptResult(
        metadata=sample_metadata,
        segments=[],
        tier_used="rss",
        raw_text="Entire raw transcript in one piece.",
    )

    srt_out = SrtExporter().export(result)
    assert srt_out.startswith("1\n00:00:00,000 --> 00:45:12,500\nEntire raw transcript in one piece.\n\n")

    vtt_out = VttExporter().export(result)
    assert vtt_out.startswith("WEBVTT\n\n00:00:00.000 --> 00:45:12.500\nEntire raw transcript in one piece.\n\n")


# =============================================================================
# JSON Exporter Tests
# =============================================================================


def test_json_exporter_roundtrip(sample_result: TranscriptResult) -> None:
    exporter = JsonExporter()
    output = exporter.export(sample_result)

    # Valid JSON parsing
    data = json.loads(output)
    assert data["metadata"]["episode_title"] == "Episode 42: Next-Gen Autonomous Agents!"
    assert data["tier_used"] == "whisper"
    assert len(data["segments"]) == 5

    # Pydantic model round-trip validation
    reloaded = TranscriptResult.model_validate_json(output)
    assert reloaded.metadata.episode_title == sample_result.metadata.episode_title
    assert len(reloaded.segments) == len(sample_result.segments)
    assert reloaded.tier_used == sample_result.tier_used


# =============================================================================
# Base Exporter Save Tests
# =============================================================================


def test_base_exporter_save(tmp_path: Path, sample_result: TranscriptResult) -> None:
    exporter = MarkdownExporter()
    out_file = tmp_path / "custom" / "subdir" / "transcript.md"

    saved_path = exporter.save(sample_result, out_file)
    assert saved_path.exists()
    assert saved_path == out_file.resolve()
    content = saved_path.read_text(encoding="utf-8")
    assert "# Episode 42: Next-Gen Autonomous Agents!" in content


# =============================================================================
# Export Manager Tests
# =============================================================================


def test_export_manager_resolve_formats() -> None:
    manager = ExportManager()

    assert manager.resolve_formats("both") == ["markdown", "prose"]
    assert manager.resolve_formats("all") == ["markdown", "prose", "srt", "vtt", "json"]
    assert manager.resolve_formats("md, txt, srt") == ["markdown", "prose", "srt"]
    assert manager.resolve_formats(["markdown", "both", "json"]) == ["markdown", "prose", "json"]

    with pytest.raises(ValueError, match="Unsupported export format"):
        manager.resolve_formats("unsupported_format")


def test_export_manager_get_output_path(sample_result: TranscriptResult, tmp_path: Path) -> None:
    manager = ExportManager()

    # Default template: {output_dir}/{show_slug}/{episode_slug}.{ext}
    md_path = manager.get_output_path(sample_result, output_dir=tmp_path, format_name="markdown")
    expected = tmp_path.resolve() / "the-ai-revolution" / "episode-42-next-gen-autonomous-agents.md"
    assert md_path == expected

    # Custom template
    custom_template = "{show_slug}/transcripts/{episode_id}.{ext}"
    custom_path = manager.get_output_path(
        sample_result,
        output_dir=tmp_path,
        format_name="srt",
        template=custom_template,
    )
    expected_custom = tmp_path.resolve() / "the-ai-revolution" / "transcripts" / "ep-42-agents.srt"
    assert custom_path == expected_custom


def test_export_manager_export_all_both(sample_result: TranscriptResult, tmp_path: Path) -> None:
    manager = ExportManager()
    saved = manager.export_all(sample_result, output_dir=tmp_path, formats="both")

    assert "markdown" in saved
    assert "prose" in saved
    assert len(saved) == 2

    assert saved["markdown"].exists()
    assert saved["prose"].exists()
    assert saved["markdown"].suffix == ".md"
    assert saved["prose"].suffix == ".txt"

    # Verify content in created files
    assert "# Episode 42" in saved["markdown"].read_text(encoding="utf-8")
    assert "Host: Welcome to the show" in saved["prose"].read_text(encoding="utf-8")


def test_export_manager_export_all_all_formats(sample_result: TranscriptResult, tmp_path: Path) -> None:
    manager = ExportManager()
    saved = manager.export_all(sample_result, output_dir=tmp_path, formats="all")

    assert set(saved.keys()) == {"markdown", "prose", "srt", "vtt", "json"}
    for fmt, path in saved.items():
        assert path.exists()
        assert path.stat().st_size > 0


def test_export_manager_custom_exporter_registration() -> None:
    class CustomCsvExporter(BaseExporter):
        format_name = "csv"
        extension = "csv"

        def export(self, result: TranscriptResult) -> str:
            return "start,end,text\n"

    manager = ExportManager()
    manager.register_exporter("csv", CustomCsvExporter())

    assert "csv" in manager.available_formats
    assert isinstance(manager.get_exporter("csv"), CustomCsvExporter)
