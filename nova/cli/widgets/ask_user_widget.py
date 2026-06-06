from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TabbedContent, TabPane
from textual.widget import Widget

from nova.cli.ask_user import QuestionData


class AskUserWizard(Widget):

    can_focus = True

    class Submitted(Message):
        def __init__(self, answers: list[tuple[str, str]], questions: list[QuestionData]) -> None:
            super().__init__()
            self.answers = answers
            self.questions = questions

    class Dismissed(Message):
        pass

    DEFAULT_CSS = """
    AskUserWizard {
        background: $background;
        border-left: tall $warning;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }

    #wiz-tabs {
        height: auto;
    }
    #wiz-tabs Tabs {
        height: 2;
    }
    #wiz-tabs Tab {
        color: $text-muted;
        padding: 0 1;
    }
    #wiz-tabs Tab:hover {
        color: $foreground;
    }
    #wiz-tabs Tab.-active {
        color: $secondary;
        text-style: bold;
    }
    #wiz-tabs TabPane {
        height: auto;
        padding: 0;
    }

    .q-header {
        color: $secondary;
        text-style: bold;
        margin: 0 0 0 0;
    }
    .q-question {
        color: $foreground;
        margin: 0 0 1 0;
    }

    .q-list {
        background: $background;
        border: solid $border-blurred;
        height: auto;
        max-height: 12;
        margin: 0 0 1 0;
    }
    .q-list > ListItem {
        padding: 0 1;
        background: $background;
    }
    .q-list > ListItem:hover {
        background: $surface;
    }
    .q-list > ListItem.--highlight {
        background: $surface;
    }
    .q-list > ListItem > Label {
        color: $foreground;
    }
    .q-list > ListItem.--highlight > Label {
        color: $secondary;
        text-style: bold;
    }

    .q-input {
        margin: 0 0 1 0;
        background: $background;
        border: tall $border-blurred;
    }
    .q-input:focus {
        border: tall $primary;
    }

    .q-buttons {
        height: auto;
        margin: 0 0 1 0;
    }
    .q-btn { width: 12; border: tall $border-blurred; }
    .q-btn-active { background: $surface; border: tall $secondary; }

    #wiz-nav {
        layout: horizontal;
        height: auto;
        padding: 0 2;
        align: right middle;
    }
    .nav-prev { color: $foreground-disabled; width: auto; margin-right: 2; }
    .nav-prev:hover { color: $foreground; }
    .nav-next { color: $secondary; text-style: bold; width: auto; }
    .nav-next:hover { color: $success; }
    .nav-next.done { color: $success; }

    .review-line {
        color: $foreground;
        margin: 0 0 0 1;
    }

    #wiz-hint {
        color: $text-disabled;
        height: 1;
    }
    """

    def __init__(self, questions: list[QuestionData]) -> None:
        super().__init__()
        self._questions = questions
        self._is_wizard = len(questions) > 1
        self._current_step = 0
        self._answers: dict[str, str] = {}
        self._selected_idx = [0] * len(questions)
        self._confirm_values = [False] * len(questions)

    # ── Compose ──────────────────────────────────────────

    def compose(self) -> ComposeResult:
        if self._is_wizard:
            with TabbedContent(id="wiz-tabs"):
                for i, question in enumerate(self._questions):
                    with TabPane(question.header or f"Step {i+1}", id=f"pane-{i}"):
                        yield from self._compose_card(question, i)
                with TabPane("Confirm", id="pane-confirm"):
                    yield Static("Confirm your answers", classes="q-header")
                    yield Static("")
                    for i, question in enumerate(self._questions):
                        yield Static(f"{i+1}. {question.header or question.id}  ", id=f"review-line-{i}", classes="review-line")
                    yield Static("")
            with Horizontal(id="wiz-nav"):
                yield Static("", id="nav-prev", classes="nav-prev", markup=True)
                yield Static("Next \u2192", id="nav-next", classes="nav-next", markup=True)
        else:
            yield from self._compose_card(self._questions[0], 0)
            yield Static("Submit", id="nav-submit", classes="nav-next", markup=True)
        yield Static(id="wiz-hint")

    def on_mount(self) -> None:
        if self._is_wizard:
            tabs = self.query_one(TabbedContent)
            tabs.active = "pane-0"
            # Disable all tabs except the first
            self._update_tab_disabled()
        self._init_card(0)
        self._update_nav()
        self._update_hint()

    def _compose_card(self, question: QuestionData, i: int) -> list[Widget]:
        widgets: list[Widget] = []
        widgets.append(Static(question.question, classes="q-question"))
        if question.input_type == "select":
            opts = question.options or []
            items = [
                ListItem(
                    Label(f"{j}. {o['label']}  {o.get('description', '')}"))
                for j, o in enumerate(opts, 1)
            ]
            widgets.append(
                ListView(*items, classes="q-list", id=f"q-list-{i}"))
        elif question.input_type == "text":
            widgets.append(Input(placeholder="Type your answer...",
                           classes="q-input", id=f"q-input-{i}"))
        elif question.input_type == "confirm":
            widgets.append(Horizontal(
                Button("Yes", id=f"q-yes-{i}", classes="q-btn"),
                Button("No", id=f"q-no-{i}", classes="q-btn"),
                classes="q-buttons",
            ))
        return widgets

    def _init_card(self, i: int) -> None:
        if i >= len(self._questions):
            self.focus()
            return
        question = self._questions[i]
        if question.input_type == "select":
            self.focus()
        elif question.input_type == "text":
            inp = self.query_one(f"#q-input-{i}", Input)
            inp.focus()
        elif question.input_type == "confirm":
            self._confirm_values[i] = False
            self._update_confirm_highlight(i)
            self.focus()

    # ── Step navigation ──────────────────────────────────

    @property
    def _is_review(self) -> bool:
        return self._is_wizard and self._current_step == len(self._questions)

    def _current_question(self) -> QuestionData | None:
        if self._is_review:
            return None
        return self._questions[self._current_step]

    def _save_current(self) -> None:
        question = self._current_question()
        if question is None:
            return
        if question.input_type == "select":
            opts = question.options or []
            idx = self._selected_idx[self._current_step]
            if 0 <= idx < len(opts):
                self._answers[question.id] = opts[idx]["label"]
        elif question.input_type == "text":
            inp = self.query_one(f"#q-input-{self._current_step}", Input)
            val = inp.value.strip()
            if val:
                self._answers[question.id] = val
            elif question.id in self._answers:
                del self._answers[question.id]
        elif question.input_type == "confirm":
            self._answers[question.id] = "yes" if self._confirm_values[self._current_step] else "no"

    def _can_advance(self) -> bool:
        question = self._current_question()
        if question is None:
            return True
        if not question.required:
            return True
        if question.input_type == "select":
            opts = question.options or []
            return len(opts) > 0
        elif question.input_type == "text":
            inp = self.query_one(f"#q-input-{self._current_step}", Input)
            return bool(inp.value.strip())
        elif question.input_type == "confirm":
            return True
        return True

    def _all_required_filled(self) -> bool:
        return all(
            question.id in self._answers
            for question in self._questions if question.required
        )

    def _go_next(self) -> None:
        self._save_current()
        tabs = self.query_one(TabbedContent)
        if self._current_step < len(self._questions) - 1:
            self._current_step += 1
            tabs.active = f"pane-{self._current_step}"
            self._update_tab_disabled()
            self._init_card(self._current_step)
            self.set_timer(0, self._ensure_card_focus)
        else:
            self._current_step = len(self._questions)
            self._refresh_review()
            tabs.active = "pane-confirm"
            self.set_timer(0, self.focus)
        self._update_nav()
        self._update_hint()

    def _go_prev(self) -> None:
        tabs = self.query_one(TabbedContent)
        if self._is_review:
            self._current_step = len(self._questions) - 1
            tabs.active = f"pane-{self._current_step}"
        elif self._current_step > 0:
            self._current_step -= 1
            tabs.active = f"pane-{self._current_step}"
        self._init_card(self._current_step)
        self.set_timer(0, self._ensure_card_focus)
        self._update_tab_disabled()
        self._update_nav()
        self._update_hint()

    def _ensure_card_focus(self) -> None:
        if self._current_step < len(self._questions):
            question = self._questions[self._current_step]
            if question.input_type == "select":
                self.focus()
            elif question.input_type == "text":
                try:
                    self.query_one(
                        f"#q-input-{self._current_step}", Input).focus()
                except Exception:
                    self.focus()

    def _update_tab_disabled(self) -> None:
        tabs = self.query_one(TabbedContent)
        for child in tabs.query(TabPane):
            tab_id = child.id or ""
            if tab_id == "pane-confirm":
                continue
            try:
                step = int(tab_id.replace("pane-", ""))
            except (ValueError, IndexError):
                continue
            child.disabled = step > self._current_step + 1

    def _refresh_review(self) -> None:
        for i, question in enumerate(self._questions):
            widget = self.query_one(f"#review-line-{i}", Static)
            answer = self._answers.get(question.id, "(not answered)")
            widget.update(f"{i+1}. {question.header or question.id}  {answer}")

    # ── UI updates ───────────────────────────────────────

    def _update_nav(self) -> None:
        if not self._is_wizard:
            return
        nav_prev = self.query_one("#nav-prev", Static)
        nav_next = self.query_one("#nav-next", Static)
        nav_prev.update("\u2190 Back" if self._current_step > 0 else "")
        if self._is_review:
            all_ok = self._all_required_filled()
            nav_next.update(
                "\u2714 Submit" if all_ok else "\u2714 Submit  [dim](fill required first)[/dim]")
            nav_next.set_classes("nav-next" + (" done" if all_ok else ""))
        else:
            nav_next.update("Next \u2192")
            nav_next.set_classes("nav-next")

    def _update_hint(self) -> None:
        hint = self.query_one("#wiz-hint")
        if self._is_review:
            hint.update("Enter Submit \u00b7 Back to edit \u00b7 Esc dismiss")
        elif self._is_wizard:
            hint.update(
                "\u2191\u2193 navigate \u00b7 Enter advance \u00b7 Esc dismiss")
        else:
            question = self._current_question()
            if question and question.input_type == "select":
                hint.update(
                    "\u2191\u2193 navigate \u00b7 Enter select \u00b7 Esc dismiss")
            elif question and question.input_type == "text":
                hint.update(
                    "Type answer \u00b7 Enter submit \u00b7 Esc dismiss")
            elif question and question.input_type == "confirm":
                hint.update(
                    "\u2190\u2192 switch \u00b7 Enter submit \u00b7 Esc dismiss")
            else:
                hint.update("Esc dismiss")

    # ── Click handling (nav / submit) ────────────────────

    async def _on_click(self, event: Click) -> None:
        target = event.widget
        if target is not None:
            tid = getattr(target, "id", "") or ""
            if tid == "nav-prev":
                event.stop()
                self._go_prev()
                return
            elif tid == "nav-next":
                event.stop()
                if self._is_review:
                    if self._all_required_filled():
                        self._submit()
                else:
                    if self._can_advance():
                        self._go_next()
                return
            elif tid == "nav-submit":
                event.stop()
                self._submit()
                return
        await super()._on_click(event)

    # ── List highlight (select cards) ────────────────────

    def _update_list_highlight(self, step: int) -> None:
        lst = self.query_one(f"#q-list-{step}", ListView)
        for i, item in enumerate(lst.children):
            cls = "--highlight"
            if i == self._selected_idx[step]:
                item.add_class(cls)
            else:
                item.remove_class(cls)

    # ── Confirm buttons ──────────────────────────────────

    def _update_confirm_highlight(self, step: int) -> None:
        val = self._confirm_values[step]
        yes_btn = self.query_one(f"#q-yes-{step}", Button)
        no_btn = self.query_one(f"#q-no-{step}", Button)
        yes_btn.classes = "q-btn q-btn-active" if val else "q-btn"
        no_btn.classes = "q-btn q-btn-active" if not val else "q-btn"

    # ── Submit ───────────────────────────────────────────

    def _submit(self) -> None:
        if not self._is_wizard:
            self._save_current()
        answers = [(qid, ans) for qid, ans in self._answers.items()]
        self.post_message(self.Submitted(answers, self._questions))

    # ── Event handlers ───────────────────────────────────

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.post_message(self.Dismissed())
            return

        # Wizard tab navigation via left/right
        if self._is_wizard and event.key in ("left", "right"):
            question = self._current_question()
            if question and question.input_type == "confirm":
                pass  # handled below
            else:
                event.stop()
                if event.key == "left":
                    self._go_prev()
                elif self._is_review:
                    self._submit()
                elif self._can_advance():
                    self._go_next()
                return

        question = self._current_question()
        if question is None:
            if self._is_wizard and event.key == "enter":
                event.stop()
                if self._all_required_filled():
                    self._submit()
            return

        if question.input_type == "select":
            opts = question.options or []
            if event.key == "up":
                event.stop()
                list_view = self.query_one(
                    f"#q-list-{self._current_step}", ListView)
                if list_view.index is not None and list_view.index > 0:
                    list_view.index -= 1
                return
            if event.key == "down":
                event.stop()
                list_view = self.query_one(
                    f"#q-list-{self._current_step}", ListView)
                if list_view.index is not None and list_view.index < len(list_view.children) - 1:
                    list_view.index += 1
                return
            elif event.key == "enter":
                list_view = self.query_one(
                    f"#q-list-{self._current_step}", ListView)
                event.stop()
                lst = self.query_one(f"#q-list-{self._current_step}", ListView)
                idx = lst.index
                self._selected_idx[self._current_step] = idx
                self._update_list_highlight(self._current_step)
                if self._is_wizard:
                    self._go_next()
                else:
                    self._submit()

        elif question.input_type == "confirm":
            if event.key == "left":
                event.stop()
                self._confirm_values[self._current_step] = True
                self._update_confirm_highlight(self._current_step)
                return
            if event.key == "right":
                event.stop()
                self._confirm_values[self._current_step] = False
                self._update_confirm_highlight(self._current_step)
                return
            if event.key == "enter":
                event.stop()
                if self._is_wizard:
                    self._go_next()
                else:
                    self._submit()
                return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        for i, question in enumerate(self._questions):
            if question.input_type != "select":
                continue
            lst = self.query_one(f"#q-list-{i}", ListView)
            if event.list_view is not lst:
                continue
            items = list(lst.children)
            idx = items.index(event.item)
            self._selected_idx[i] = idx
            self._update_list_highlight(i)
            if self._is_wizard:
                self._current_step = i
                self._go_next()
            else:
                self._submit()
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        for i, question in enumerate(self._questions):
            if question.input_type != "text":
                continue
            inp = self.query_one(f"#q-input-{i}", Input)
            if event.input is not inp:
                continue
            self._current_step = i
            if self._is_wizard:
                self._go_next()
            else:
                self._submit()
            return

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id if event.pane else ""
        if pane_id.startswith("pane-"):
            idx_str = pane_id[5:]
            if idx_str == "confirm":
                self._current_step = len(self._questions)
                self._refresh_review()
                self._update_nav()
                self._update_hint()
            else:
                try:
                    step = int(idx_str)
                except ValueError:
                    return
                if step != self._current_step:
                    self._current_step = step
                    self._init_card(step)
                    self._update_nav()
                    self._update_hint()
        self.set_timer(0, self._ensure_card_focus)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("q-yes-"):
            for i in range(len(self._questions)):
                if btn_id == f"q-yes-{i}":
                    self._confirm_values[i] = True
                    self._update_confirm_highlight(i)
                    event.stop()
                    return
        elif btn_id.startswith("q-no-"):
            for i in range(len(self._questions)):
                if btn_id == f"q-no-{i}":
                    self._confirm_values[i] = False
                    self._update_confirm_highlight(i)
                    event.stop()
                    return
