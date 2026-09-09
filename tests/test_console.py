"""Unit tests for UIConsole, theme, and Rich output formatting."""

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from podcast_cli.ui.console import (
    UIConsole,
    console as global_console,
    error,
    info,
    panel,
    rule,
    status_spinner,
    success,
    table,
    warning,
)
from podcast_cli.ui.theme import THEME_STYLES, custom_theme


@pytest.fixture
def test_console() -> UIConsole:
    """Fixture providing a fresh UIConsole instance configured to record output."""
    stdout_c = Console(theme=custom_theme, record=True, width=120, force_terminal=True)
    stderr_c = Console(theme=custom_theme, record=True, width=120, force_terminal=True, stderr=True)
    return UIConsole(stdout_console=stdout_c, stderr_console=stderr_c)


class TestUITheme:
    def test_theme_contains_required_styles(self) -> None:
        """Verify that custom theme contains all required semantic styles."""
        assert "info" in THEME_STYLES
        assert "success" in THEME_STYLES
        assert "warning" in THEME_STYLES
        assert "error" in THEME_STYLES
        assert "error_panel" in THEME_STYLES
        assert "highlight" in THEME_STYLES
        assert "banner" in THEME_STYLES
        assert "progress" in THEME_STYLES

    def test_custom_theme_instance(self) -> None:
        """Verify custom_theme is a valid rich Theme instance."""
        assert custom_theme is not None
        assert custom_theme.styles["info"].color.name == "cyan"
        assert custom_theme.styles["success"].color.name == "green"
        assert custom_theme.styles["warning"].color.name == "yellow"
        assert custom_theme.styles["error"].color.name == "red"


class TestUIConsoleStdout:
    def test_info_formatting(self, test_console: UIConsole) -> None:
        test_console.info("Fetching podcast feed metadata...")
        output = test_console.export_text()
        assert "Fetching podcast feed metadata..." in output
        assert "ℹ" in output
        # Verify stderr remained empty
        assert test_console.export_stderr_text() == ""

    def test_info_with_title_and_custom_prefix(self, test_console: UIConsole) -> None:
        test_console.info("Huberman Lab", title="Found Feed", prefix="→ ")
        output = test_console.export_text()
        assert "Found Feed:" in output
        assert "Huberman Lab" in output
        assert "→" in output

    def test_info_with_renderable(self, test_console: UIConsole) -> None:
        text = Text("Styled Renderable Content", style="bold cyan")
        test_console.info(text, title="Renderable")
        output = test_console.export_text()
        assert "Renderable" in output
        assert "Styled Renderable Content" in output

    def test_success_formatting(self, test_console: UIConsole) -> None:
        test_console.success("Transcript saved successfully.")
        output = test_console.export_text()
        assert "Transcript saved successfully." in output
        assert "✔" in output
        assert test_console.export_stderr_text() == ""

    def test_success_with_title(self, test_console: UIConsole) -> None:
        test_console.success("/path/to/transcript.md", title="Saved")
        output = test_console.export_text()
        assert "Saved:" in output
        assert "/path/to/transcript.md" in output

    def test_warning_formatting(self, test_console: UIConsole) -> None:
        test_console.warning("RSS transcript unavailable, falling back to YouTube.")
        output = test_console.export_text()
        assert "RSS transcript unavailable, falling back to YouTube." in output
        assert "⚠" in output
        assert test_console.export_stderr_text() == ""

    def test_warning_with_title(self, test_console: UIConsole) -> None:
        test_console.warning("Large audio file detected", title="Pre-flight Warning")
        output = test_console.export_text()
        assert "Pre-flight Warning:" in output
        assert "Large audio file detected" in output

    def test_rule(self, test_console: UIConsole) -> None:
        test_console.rule("Episode Details")
        output = test_console.export_text()
        assert "Episode Details" in output


class TestUIConsoleStderr:
    def test_error_logged_to_stderr_panel(self, test_console: UIConsole) -> None:
        test_console.error("Failed to connect to RSS feed.", title="Connection Error")
        stdout_output = test_console.export_text()
        stderr_output = test_console.export_stderr_text()

        # Stdout must be completely empty
        assert stdout_output == ""
        # Stderr must contain the error title and message inside panel borders
        assert "Connection Error" in stderr_output
        assert "Failed to connect to RSS feed." in stderr_output

    def test_error_with_exception(self, test_console: UIConsole) -> None:
        exc = ValueError("Invalid URL scheme")
        test_console.error("Discovery failed", exception=exc)
        stderr_output = test_console.export_stderr_text()

        assert "Discovery failed" in stderr_output
        assert "ValueError" in stderr_output
        assert "Invalid URL scheme" in stderr_output

    def test_error_with_exception_object(self, test_console: UIConsole) -> None:
        exc = RuntimeError("Whisper model loading failed")
        test_console.error(exc)
        stderr_output = test_console.export_stderr_text()

        assert "RuntimeError" in stderr_output
        assert "Whisper model loading failed" in stderr_output

    def test_error_without_panel(self, test_console: UIConsole) -> None:
        test_console.error("Quick error message", panel=False)
        stderr_output = test_console.export_stderr_text()

        assert "Quick error message" in stderr_output
        assert "✖" in stderr_output


class TestUIConsolePanelAndTable:
    def test_panel_creation_and_printing(self, test_console: UIConsole) -> None:
        p = test_console.panel(
            "Pre-flight gatekeeper summary:\nTotal: 5 episodes\nDuration: 4h 12m",
            title="Summary",
            subtitle="Dry-run",
            border_style="cyan",
            print_out=True,
        )
        assert isinstance(p, Panel)
        output = test_console.export_text()
        assert "Summary" in output
        assert "Pre-flight gatekeeper summary" in output
        assert "4h 12m" in output

    def test_panel_without_printing(self, test_console: UIConsole) -> None:
        p = test_console.panel("Silent panel", title="Hidden", print_out=False)
        assert isinstance(p, Panel)
        assert test_console.export_text() == ""

    def test_table_creation_and_printing(self, test_console: UIConsole) -> None:
        tbl = test_console.table(
            title="Podcast Search Results",
            columns=[
                ("Index", {"justify": "center"}),
                ("Show Title", {"justify": "left"}),
                "Episodes",
            ],
            rows=[
                [1, "The Daily", 1420],
                [2, "Huberman Lab", 210],
            ],
            print_out=True,
        )
        assert isinstance(tbl, Table)
        output = test_console.export_text()
        assert "Podcast Search Results" in output
        assert "The Daily" in output
        assert "Huberman Lab" in output
        assert "1420" in output

    def test_table_without_printing(self, test_console: UIConsole) -> None:
        tbl = test_console.table(
            columns=["Col A", "Col B"],
            rows=[["A1", "B1"]],
            print_out=False,
        )
        assert isinstance(tbl, Table)
        assert test_console.export_text() == ""

    def test_status_spinner_context_manager(self, test_console: UIConsole) -> None:
        executed = False
        with test_console.status_spinner("Downloading audio..."):
            executed = True
        assert executed is True


class TestModuleLevelHelpers:
    def test_module_level_exports(self) -> None:
        assert callable(info)
        assert callable(success)
        assert callable(warning)
        assert callable(error)
        assert callable(panel)
        assert callable(table)
        assert callable(status_spinner)
        assert callable(rule)
        assert global_console is not None
