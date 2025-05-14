from typing import Any

import yaml
from auryn import Junk, Lines
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from vynil import Renderer


def meta_content(junk: Junk) -> None:
    if Renderer.CONTENT not in junk.meta_state:
        raise ValueError("no content (this meta function can only be used inside a container)")
    content: Lines = junk.meta_state[Renderer.CONTENT]
    junk.proceed(content.snap(junk.line.indent))


def eval_get(junk: Junk, index: int) -> Any:
    globals_: list[Any] = junk.meta_state[Renderer.GLOBALS]
    result = globals_[index]
    return result


def eval_restore_globals(junk: Junk, globals_before: dict[str, Any], globals_after: dict[str, Any]) -> None:
    globals_after.clear()
    globals_after.update(globals_before)


def meta_yaml(junk: Junk) -> None:
    globals_: list[Any] = junk.meta_state.setdefault(Renderer.GLOBALS, [])
    globals_.append(yaml.safe_load(junk.line.children.snap(0).to_string()))
    junk.emit_code(f"globals().update(get({len(globals_) - 1}))")


def meta_title(junk: Junk, title: str) -> None:
    junk.emit_code(f"title({junk.line.indent}, {title!r})")


def eval_title(junk: Junk, indent: int, title: str) -> None:
    renderer = Renderer.from_junk(junk)
    chapter = renderer.current_chapter
    if not chapter:
        raise ValueError("no chapter set (call renderer.set_chapter() first)")
    chapter.title = title
    junk.emit(indent, f"<h1 id={chapter.id!r}>{title}</h1>")


def meta_section(junk: Junk, title: str) -> None:
    junk.emit_code(f"section({junk.line.indent}, {title!r})")


def eval_section(junk: Junk, indent: int, title: str) -> None:
    renderer = Renderer.from_junk(junk)
    section = renderer.add_section(title)
    junk.emit(indent, f"<h2 id={section.id!r}>{title}</h2>")


def meta_code(junk: Junk, language: str | None = None) -> None:
    renderer = Renderer.from_junk(junk)
    if language is None:
        language = renderer.book.default_code_language
    code = junk.line.children.snap(0).to_string().rstrip()
    lexer = get_lexer_by_name(language)
    formatter = HtmlFormatter()
    html = highlight(code, lexer, formatter)
    first_line, *lines = html.splitlines()
    junk.emit_text(junk.line.indent, first_line, interpolate=False)
    for line in lines:
        junk.emit_text(0, line, interpolate=False)
