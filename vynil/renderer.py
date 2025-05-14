from __future__ import annotations

import contextlib
import http.server
import pathlib
import re
import time
from typing import Any, Callable, ClassVar, cast

import watchdog.events
import watchdog.observers
from auryn import Junk, render
from fontTools.ttLib import TTFont

from .model import Asset, AssetType, Book, Chapter, ExtensionType, Font, Format, Section

ROOT = pathlib.Path(__file__).parent
COMPONENTS_DIRECTORY = ROOT / "components"
Junk.builtins_directories.append(ROOT / "meta")
FONTFACE = """
@font-face {{
    font-family: '{font.family}';
    src: url('../{font.url}') format('{font.type}');
    font-weight: {font.weight};
    font-style: {font.style};
}}
"""


class Renderer:

    all: ClassVar[dict[Format, type[Renderer]]] = {}
    format: ClassVar[Format]
    template: ClassVar[str | pathlib.Path]
    fonts_styles_filename: ClassVar[str] = "fonts.css"
    module_on_load_name: ClassVar[str] = "on_load"
    module_render_name: ClassVar[str] = "render"
    common_css_filename: ClassVar[pathlib.Path] = ROOT / "common.css"
    syntax_highlighting_style: ClassVar[pathlib.Path] = ROOT / "syntax-highlighting.css"

    GLOBALS: ClassVar[str] = "globals"
    CONTENT: ClassVar[str] = "content"

    def __init_subclass__(cls) -> None:
        format = getattr(cls, "format", None)
        if format is None:
            formats = set(Format) - set(cls.all)
            raise TypeError(f"renderer {cls.__name__} must define one of the following formats: {', '.join(formats)}")
        if format in cls.all:
            other = cls.all[format]
            raise TypeError(
                f"renderer {cls.__name__} cannot be registered for format {format} "
                f"because it is already registered for {other.__name__}"
            )
        cls.all[format] = cls

    def __init__(self, book: Book) -> None:
        self.book = book
        self.current_chapter: Chapter | None = None
        self.current_section: Section | None = None
        self.styles: dict[str, Asset] = {}
        self.scripts: dict[str, Asset] = {}
        self.images: dict[str, Asset] = {}
        self.fonts: dict[str, Asset] = {}
        self.files: dict[str, Asset] = {}
        self._available_images: dict[str, Asset] = {}
        self._fonts_style = Asset(
            name=self.fonts_styles_filename,
            type=AssetType.style,
            mimetype="text/css",
            data=b"",
        )
        self._fonts: list[Font] = []
        self.add_builtin_assets()
        seen: set[str] = set()
        for asset in book.assets:
            if not asset.formats or self.format in asset.formats:
                if asset.name in seen:
                    raise ValueError(f"multiple assets with the same name: {asset.name}")
                seen.add(asset.name)
                match asset.type:
                    case AssetType.image:
                        self._available_images[asset.name] = asset
                    case AssetType.style:
                        self.styles[asset.url] = asset
                    case AssetType.script:
                        self.scripts[asset.url] = asset
                    case AssetType.font:
                        self._add_font(asset)

    @classmethod
    def create(cls, format: Format, book: Book) -> Renderer:
        if format not in cls.all:
            raise ValueError(f"no renderer registered for format {format}")
        return cls.all[format](book)

    @classmethod
    def from_junk(cls, junk: Junk) -> Renderer:
        return junk.meta_namespace["renderer"]

    @property
    def assets(self) -> dict[str, Asset]:
        return {
            **self.images,
            **self.styles,
            **self.scripts,
            **self.fonts,
            **self.files,
        }

    def render(self, template: str | pathlib.Path | None = None, /, **context: Any) -> bytes:
        if template is None:
            template = self.template
        components = self.collect_components()
        context.update(renderer=self, book=self.book)
        html = render(
            template,
            load=[
                "vynil",
                components,
            ],
            meta_context=context,
            **context,
        )
        self.postprocess_assets()
        return html.encode()

    def render_display(self, template: str | pathlib.Path | None = None, /, **context: Any) -> str:
        return self.render(template, **context).decode()

    def generate(
        self,
        path: str | pathlib.Path,
        *,
        template: str | pathlib.Path | None = None,
        **context: Any,
    ) -> None:
        raise NotImplementedError()

    def serve(self, port: int, *, template: str | pathlib.Path | None = None, **context: Any) -> None:
        server = WebServer(("", port), self, template, context)
        with server:
            if self.book.path:
                observer = watchdog.observers.Observer()
                observer.schedule(Reloader(server), str(self.book.path), recursive=True)
                observer.start()
            print(f"http://localhost:{port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                observer.stop()
                observer.join()

    def add_builtin_assets(self) -> None:
        self.styles[self._fonts_style.url] = self._fonts_style
        self.add_style(self.common_css_filename.name, self.common_css_filename.read_text())
        self.add_style(self.syntax_highlighting_style.name, self.syntax_highlighting_style.read_text())

    def postprocess_assets(self) -> None:
        fonts_css = []
        for font in self._fonts:
            fonts_css.append(FONTFACE.format(font=font))
        self._fonts_style.data = "\n".join(fonts_css).strip().encode()

    def collect_components(self) -> dict[str, Callable[[Junk, Any], None]]:
        components = {}
        for component in COMPONENTS_DIRECTORY.iterdir():
            components[f"meta_{component.stem}"] = self.create_component(component)
        for extension in self.book.extensions:
            if extension.type == ExtensionType.module:
                module: dict[str, Any] = {}
                exec(extension.text, module)
                on_load = getattr(module, self.module_on_load_name, None)
                if on_load is not None:
                    on_load(self)
                render = getattr(module, self.module_render_name, None)
                if render is not None:
                    components[f"meta_{extension.name}"] = render
            else:
                template = extension.path or extension.text
                components[f"meta_{extension.name}"] = self.create_component(template)
        return components

    def create_component(self, template: str | pathlib.Path) -> Callable[[Junk, Any], None]:
        def meta_component(junk: Junk, arg: str | None = None) -> None:
            junk.meta_state[self.CONTENT] = junk.line.children
            component_junk = junk.derive(template, with_namespace=True)
            component_junk.lines.snap(junk.line.indent)
            component_junk.transpile()
            self.transpile(junk, component_junk.to_string(), arg=arg)
            del junk.meta_state[self.CONTENT]

        return meta_component

    def transpile(self, junk: Junk, code: str, /, **kwargs: Any) -> None:
        globals_: list[Any] = junk.meta_state.setdefault(self.GLOBALS, [])
        globals_.append(kwargs)
        junk.emit_code("globals_before = globals().copy()")
        junk.emit_code(f"globals().update(get({len(globals_) - 1}))")
        junk.emit_code(code, add_source_comment=False)
        junk.emit_code("restore_globals(globals_before, globals())")

    def set_chapter(self, chapter_id: str) -> None:
        for chapter in self.book.chapters:
            if chapter.id == chapter_id:
                self.current_chapter = chapter
                return
        raise ValueError(
            f"chapter {chapter_id!r} not found "
            f"(available chapters are {', '.join(chapter.id for chapter in self.book.chapters)})"
        )

    def add_section(self, title: str) -> Section:
        if not self.current_chapter:
            raise ValueError(f"cannot add section {title!r} with no chapter set")
        section_id = f"{self.current_chapter.id}-{_slugify(title)}"
        section = Section(id=section_id, title=title)
        self.current_chapter.sections[section_id] = section
        self.current_section = section
        return section

    def image_url(self, image_name: str) -> str:
        if image_name not in self._available_images:
            raise ValueError(
                f"asset {image_name!r} not found (available assets are {', '.join(self._available_images)})"
            )
        asset = self._available_images[image_name]
        self.images[asset.url] = asset
        return asset.url

    def add_style(self, name: str, css: str) -> str:
        if name in self.styles:
            raise ValueError(f"style {name!r} already exists")
        asset = Asset(
            name=name,
            type=AssetType.style,
            mimetype="text/css",
            data=css.encode(),
        )
        self.styles[asset.url] = asset
        return asset.url

    def add_script(self, name: str, js: str) -> str:
        if name in self.scripts:
            raise ValueError(f"script {name!r} already exists")
        asset = Asset(
            name=name,
            type=AssetType.script,
            mimetype="text/javascript",
            data=js.encode(),
        )
        self.scripts[asset.url] = asset
        return asset.url

    def _add_font(self, asset: Asset) -> None:
        font_type = asset.mimetype.split("/")[1]
        ttf = TTFont(asset.path)
        family = self._get_font_name(ttf, 16) or self._get_font_name(ttf, 1)
        if not family:
            raise ValueError(f"unable to extract font {asset.name!r} name")
        subfamily = self._get_font_name(ttf, 17) or self._get_font_name(ttf, 2)
        style = self._get_font_style(ttf, subfamily)
        weight = self._get_font_weight(ttf, subfamily)
        font = Font(url=asset.url, type=font_type, family=family, weight=weight, style=style)
        self._fonts.append(font)
        self.fonts[font.url] = asset

    def _get_font_name(self, ttf: TTFont, name_id: int) -> str | None:
        for record in ttf["name"].names:
            if record.nameID == name_id:
                with contextlib.suppress(Exception):
                    return record.toUnicode()
        return None

    def _get_font_style(self, ttf: TTFont, subfamily: str | None) -> str:
        if subfamily and "italic" in subfamily.lower():
            return "italic"
        return "normal"

    def _get_font_weight(self, ttf: TTFont, subfamily: str | None) -> int:
        subfamily = self._get_font_name(ttf, 16) or self._get_font_name(ttf, 1)
        if subfamily:
            match subfamily.lower():
                case "thin" | "ultralight":
                    return 100
                case "extralight" | "ultralight":
                    return 200
                case "light":
                    return 300
                case "regular" | "normal":
                    return 400
                case "medium":
                    return 500
                case "semibold" | "demibold":
                    return 600
                case "bold" | "extrabold" | "ultrabold":
                    return 700
                case "black" | "heavy":
                    return 900
        with contextlib.suppress(Exception):
            return int(ttf["OS/2"].usWeightClass)
        return 400


class WebServer(http.server.HTTPServer):

    def __init__(
        self,
        server_address: tuple[str, int],
        renderer: Renderer,
        template: str | pathlib.Path | None,
        context: dict[str, Any],
    ) -> None:
        super().__init__(server_address, WebHandler)
        self.allow_reuse_address = True
        self.renderer = renderer
        self.template = template
        self.context = context
        self.html = self.render()

    def render(self) -> str:
        return self.renderer.render_display(self.template, **self.context)

    def reload(self) -> None:
        if self.renderer.book.path:
            book = Book.from_directory(self.renderer.book.path)
            self.renderer = self.renderer.create(self.renderer.format, book)
            self.html = self.render()


class WebHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self) -> None:
        server: WebServer = cast(WebServer, self.server)
        path = self.path.strip("/")
        if not path:
            self.send("text/html", server.html.encode())
        elif path in server.renderer.assets:
            asset = server.renderer.assets[path]
            self.send(asset.mimetype, asset.data)
        else:
            self.send_404()

    def send(self, mimetype: str, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-type", mimetype)
        self.send_header("Content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_404(self) -> None:
        self.send_response(404)
        self.end_headers()


class Reloader(watchdog.events.FileSystemEventHandler):

    def __init__(self, server: WebServer) -> None:
        self.server = server

    def on_modified(self, event):
        print("reloading book... ", end="")
        started = time.time()
        self.server.reload()
        print(f"done in {time.time() - started:0.2f} seconds")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).replace(" ", "-")
