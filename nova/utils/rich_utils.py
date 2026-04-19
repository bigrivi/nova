from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme

theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
})

console = Console(theme=theme)


def print_markdown(content: str, title: str = "") -> None:
    md = Markdown(content)
    if title:
        console.print(Panel(md, title=title, border_style="blue"))
    else:
        console.print(md)


def print_error(message: str) -> None:
    console.print(f"[error]{message}[/error]")


def print_success(message: str) -> None:
    console.print(f"[success]{message}[/success]")


def print_info(message: str) -> None:
    console.print(f"[info]{message}[/info]")
