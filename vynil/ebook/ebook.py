import pathlib
import tempfile
from typing import Any, ClassVar

from ebooklib import epub

from ..model import Asset, AssetType, Format
from ..renderer import Renderer

ROOT = pathlib.Path(__file__).parent


class Ebook(Renderer):

    format: ClassVar[Format] = Format.ebook
    template: ClassVar[pathlib.Path] = ROOT / "ebook.html"
    ebook_mimetypes: ClassVar[dict[str, str]] = {
        "font/ttf": "application/vnd.ms-opentype",
        "font/otf": "application/vnd.ms-opentype",
        "font/woff": "application/font-woff",
    }
    display_template: ClassVar[pathlib.Path] = ROOT / "ebook_display.html"
    ebook_style: ClassVar[pathlib.Path] = ROOT / "ebook.css"
    jszip_script: ClassVar[pathlib.Path] = ROOT / "jszip.min.js"
    epubjs_script: ClassVar[pathlib.Path] = ROOT / "epub.min.js"
    ebook_asset_name: ClassVar[str] = "book.epub"

    def render(self, template: str | pathlib.Path | None = None, /, **context: Any) -> bytes:
        ebook = epub.EpubBook()
        ebook.set_identifier(self.book.identifier)
        ebook.set_title(self.book.title)
        ebook.set_language(self.book.language_code)
        ebook.prefixes.append("mathml: http://www.w3.org/1998/Math/MathML")
        for author in self.book.authors:
            ebook.add_author(author)
        toc: list[epub.Link] = []
        chapters: list[epub.EpubHtml] = []
        chapter_htmls: list[bytes] = []
        for chapter in self.book.chapters:
            chapter_html = super().render(template, chapter=chapter, **context)
            chapter_htmls.append(chapter_html)
        styles: list[epub.EpubItem] = []
        for asset in self.assets.values():
            mimetype = self.ebook_mimetypes.get(asset.mimetype, asset.mimetype)
            item = epub.EpubItem(uid=asset.name, file_name=asset.url, media_type=mimetype, content=asset.data)
            ebook.add_item(item)
            if asset.type == AssetType.style:
                styles.append(item)
        for chapter, chapter_html in zip(self.book.chapters, chapter_htmls):
            chapter_file = f"chapter_{chapter.number:02}.xhtml"
            epub_chapter = epub.EpubHtml(file_name=chapter_file, content=chapter_html)
            epub_chapter.title = chapter.title
            epub_chapter.id = chapter.id
            for style in styles:
                epub_chapter.add_link(href=style.file_name, rel="stylesheet", type="text/css")
            if b"<math" in chapter_html:
                epub_chapter.properties.append("mathml")
            ebook.add_item(epub_chapter)
            toc.append(epub.Link(chapter_file, chapter.title, chapter.id))
            chapters.append(epub_chapter)
        ebook.toc = toc
        ebook.spine = ["nav", *chapters]
        ebook.add_item(epub.EpubNcx())
        ebook.add_item(epub.EpubNav())
        with tempfile.NamedTemporaryFile(suffix=".epub") as fp:
            epub.write_epub(fp.name, ebook)
            return open(fp.name, "rb").read()

    def render_display(self, template: str | pathlib.Path | None = None, /, **context: Any) -> str:
        if template is None:
            template = self.display_template
        asset = Asset(
            name=self.ebook_asset_name,
            type=AssetType.file,
            mimetype="application/epub+zip",
            data=self.render(**context),
        )
        jszip_url = self.add_script(self.jszip_script.name, self.jszip_script.read_text())
        epubjs_url = self.add_script(self.epubjs_script.name, self.epubjs_script.read_text())
        self.files[asset.url] = asset
        html = super().render(
            template,
            ebook_url=asset.url,
            jszip_url=jszip_url,
            epubjs_url=epubjs_url,
            **context,
        )
        return html.decode()

    def generate(
        self,
        path: str | pathlib.Path,
        *,
        template: str | pathlib.Path | None = None,
        **context: Any,
    ) -> None:
        path = pathlib.Path(path)
        epub = self.render(template, **context)
        if not path.suffix == ".epub":
            path = path.with_suffix(".epub")
        path.write_bytes(epub)

    def serve(self, port: int, *, template: str | pathlib.Path | None = None, **context: Any) -> None:
        super().serve(port, template=template, **context)

    def add_builtin_assets(self) -> None:
        super().add_builtin_assets()
        self.add_style(self.ebook_style.name, self.ebook_style.read_text())
        self.add_script(self.epubjs_script.name, self.epubjs_script.read_text())
