#!/usr/bin/env python3
"""
Demo script to preview AskUserQuestion styles in terminal.

Run: python -m nova.cli.demo.demo_ask_user
Keys: 1/2/3/4 switch scenes, q quit

To use a different theme:
    TEXTUAL_THEME=nord python -m nova.cli.demo.demo_ask_user
    TEXTUAL_THEME=catppuccin-mocha python -m nova.cli.demo.demo_ask_user
"""
from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from nova.cli.widgets import AskUserQuestion
from nova.cli.ask_user import QuestionData


SCENES = {
    "1": ("Single - Select", [
        QuestionData(
            id="q1",
            header="Framework",
            question="Which framework do you prefer?",
            input_type="select",
            options=[
                {"label": "Textual", "description": "Build TUI apps"},
                {"label": "Rich", "description": "Terminal rendering"},
                {"label": "Prompt Toolkit", "description": "CLI building"},
            ],
        )
    ]),
    "2": ("Single - Text", [
        QuestionData(
            id="q2",
            header="Name",
            question="What's your name?",
            input_type="text",
        )
    ]),
    "3": ("Single - Confirm", [
        QuestionData(
            id="q3",
            header="Confirm",
            question="Are you sure you want to proceed?",
            input_type="confirm",
        )
    ]),
    "4": ("Multi-step Wizard", [
        QuestionData(
            id="w1",
            header="Backend",
            question="Choose your database backend:",
            input_type="select",
            options=[
                {"label": "PostgreSQL", "description": "Advanced, production-ready"},
                {"label": "MySQL", "description": "Popular, reliable"},
                {"label": "SQLite", "description": "Lightweight, file-based"},
            ],
        ),
        QuestionData(
            id="w2",
            header="Port",
            question="Which port to use?",
            input_type="text",
        ),
        QuestionData(
            id="w3",
            header="Deploy",
            question="Enable auto-deploy?",
            input_type="confirm",
        ),
    ]),
    "5": ("Multi-Select", [
        QuestionData(
            id="m1",
            header="Languages",
            question="Which programming languages do you know?",
            input_type="select",
            multiple=True,
            options=[
                {"label": "Python", "description": "General-purpose, scripting"},
                {"label": "TypeScript", "description": "Web, Node.js"},
                {"label": "Rust", "description": "Systems, performance"},
                {"label": "Go", "description": "Cloud, microservices"},
            ],
        )
    ]),
}


class DemoApp(App):
    CSS = """
    Screen {
        background: $background;
    }
    #scene-picker {
        dock: top;
        height: 3;
        background: $panel;
        padding: 1 2;
        color: $foreground;
    }
    #scene-content {
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("1", "show_scene('1')", "1.Select"),
        ("2", "show_scene('2')", "2.Text"),
        ("3", "show_scene('3')", "3.Confirm"),
        ("4", "show_scene('4')", "4.Wizard"),
        ("5", "show_scene('5')", "5.Multi"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, theme: str = "textual-dark") -> None:
        super().__init__()
        self.theme = theme

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Demo: Press [cyan]1[/]/[cyan]2[/]/[cyan]3[/]/[cyan]4[/]/[cyan]5[/] to switch, [red]q[/] to quit",
            id="scene-picker",
        )
        with Vertical(id="scene-content"):
            yield Static("Select a scene above")

    def action_show_scene(self, key: str) -> None:
        container = self.query_one("#scene-content")
        container.remove_children()

        title, questions = SCENES[key]
        container.mount(Static(f"[bold cyan]{title}[/]", classes="step-header"))
        wizard = AskUserQuestion(questions)
        container.mount(wizard)

    def on_ask_user_question_submitted(self, event: AskUserQuestion.Submitted) -> None:
        self.notify(f"Submitted: {event.answers}")

    def on_ask_user_question_dismissed(self, event: AskUserQuestion.Dismissed) -> None:
        self.notify("Dismissed")

    def on_mount(self) -> None:
        self.action_show_scene("1")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo AskUserQuestion with Textual themes")
    parser.add_argument("--theme", default="textual-dark",
                        help="Textual theme to use (default: textual-dark)")
    args = parser.parse_args()
    DemoApp(theme=args.theme).run()
