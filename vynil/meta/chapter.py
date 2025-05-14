import re
import shlex
from typing import Callable, Match, Pattern

import latex2mathml.converter
from auryn import Junk

CHAPTER = "chapter"
OPEN_PARAGRAPH = "open_paragraph"
ELEMENT_REGEX = re.compile(
    r"""
    ^
    ([a-z])*
    (\#[a-zA-Z0-9_-]+)?
    (\.[a-zA-Z0-9_.-]+)?
    \s+
    (.*)
    $
""",
    flags=re.VERBOSE,
)
YANKED_REGEX = re.compile(r"YANKED_(\d+)")
inline_styles: list[tuple[int, Pattern, bool, Callable[[Match], str]]] = []


def on_load(junk: Junk) -> None:
    junk.transpilers[""] = transpile_markdown
    junk.meta_callbacks.append(close_paragraph)


def transpile_markdown(junk: Junk, content: str) -> None:
    if not content:
        close_paragraph(junk)
        return
    elif content.startswith("<"):
        close_paragraph(junk)
        junk.emit_text(junk.line.indent, content)
        junk.proceed()
        return
    match = ELEMENT_REGEX.match(content)
    if match:
        close_paragraph(junk)
        tag, id, classes, attributes = match.groups()
        if not tag:
            tag = "div"
        attributes = parse_attributes(id, classes, attributes)
        if junk.line.children:
            junk.emit_text(junk.line.indent, f"<{tag}{attributes}>")
            junk.proceed(junk.line.children.snap(junk.line.indent + 4))
            junk.emit_text(junk.line.indent, f"</{tag}>")
        else:
            junk.emit_text(junk.line.indent, f"<{tag}{attributes} />")
    else:
        open_paragraph(junk)
        yanked: list[str] = []
        for _, pattern, final, style in sorted(inline_styles, key=lambda style: -style[0]):
            if final:
                content = pattern.sub(yank(style, yanked), content)
            content = pattern.sub(style, content)
        if yanked:
            content = YANKED_REGEX.sub(put_back(yanked), content)
        junk.emit_text(junk.line.indent + 4, content)
        junk.proceed(junk.line.children.snap(junk.line.indent + 4))


def inline_style(
    pattern: str, priority: int = 0, final: bool = False
) -> Callable[[Callable[[Match], str]], Callable[[Match], str]]:
    def decorator(style: Callable[[Match], str]) -> Callable[[Match], str]:
        inline_styles.append((priority, re.compile(pattern), final, style))
        return style

    return decorator


@inline_style(r"`(.+?)`", priority=2, final=True)
def code(match: Match) -> str:
    return f"<code>{match.group(1)}</code>"


@inline_style(r"\$(.+?)\$", priority=1, final=True)
def math(match: Match) -> str:
    return latex2mathml.converter.convert(match.group(1))


@inline_style(r"\*\*(.+?)\*\*")
def bold(match: Match) -> str:
    return f"<strong>{match.group(1)}</strong>"


@inline_style(r"\*(.+?)\*")
def italic(match: Match) -> str:
    return f"<em>{match.group(1)}</em>"


@inline_style(r"__(.+?)__")
def underline(match: Match) -> str:
    return f"<u>{match.group(1)}</u>"


@inline_style(r"--(.+?)--")
def strikethrough(match: Match) -> str:
    return f"<s>{match.group(1)}</s>"


@inline_style(r"\[(.+?)\]\((.+?)\)")
def link(match: Match) -> str:
    text, url = match.groups()
    if url.startswith("#") and not url.startswith("#chapter-"):
        url = f"#{{renderer.current_chapter.id}}-{url[1:]}"
    elif not url.startswith("http"):
        url = f"https://{url}"
    return f'<a href="{url}">{text}</a>'


def parse_attributes(id: str | None, classes: str | None, attributes: str) -> str:
    output: list[str] = []
    if id:
        output.append(f"id='{id!r}'")
    if classes:
        output.append(f"class='{' '.join(classes.split('.'))}'")
    if attributes:
        for attribute in shlex.split(attributes):
            if "=" in attribute:
                key, value = attribute.split("=", 1)
                value = value.strip("\"'")
                output.append(f"{key}={value!r}")
            else:
                output.append(f"{attribute}={attribute!r}")
    if not output:
        return ""
    return f" {''.join(output)}"


def close_paragraph(junk: Junk) -> None:
    open_paragraph = junk.meta_state.get(OPEN_PARAGRAPH, False)
    if open_paragraph:
        indent = junk.line.indent if junk.has_line else 0
        junk.emit_text(indent, "</p>")
        junk.meta_state[OPEN_PARAGRAPH] = False


def open_paragraph(junk: Junk) -> None:
    open_paragraph = junk.meta_state.get(OPEN_PARAGRAPH, False)
    if not open_paragraph:
        junk.emit_text(junk.line.indent, "<p>")
        junk.meta_state[OPEN_PARAGRAPH] = True


def yank(style: Callable[[Match], str], yanked: list[str]) -> Callable[[Match], str]:
    def yank(match: Match) -> str:
        yanked.append(style(match))
        return f"YANKED_{len(yanked) - 1}"

    return yank


def put_back(yanked: list[str]) -> Callable[[Match], str]:
    def put_back(match: Match) -> str:
        return yanked[int(match.group(1))]

    return put_back
