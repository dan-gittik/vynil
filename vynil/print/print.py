import contextlib
import pathlib
import tempfile
from typing import Any, ClassVar, Iterator

from playwright.sync_api import Page, sync_playwright

from ..model import Format
from ..renderer import Renderer

ROOT = pathlib.Path(__file__).parent


class Print(Renderer):

    format: ClassVar[Format] = Format.print
    template: ClassVar[pathlib.Path] = ROOT / "print.html"
    print_style: ClassVar[pathlib.Path] = ROOT / "print.css"
    pagedjs_script: ClassVar[pathlib.Path] = ROOT / "paged.polyfill.min.js"
    pagedjs_style: ClassVar[pathlib.Path] = ROOT / "paged.interface.css"

    def render(self, template: str | pathlib.Path | None = None, /, **context: Any) -> bytes:
        html = super().render(template, **context, toc={})
        toc = self.extract_toc(html)
        return super().render(template, **context, toc=toc)

    def generate(
        self,
        path: str | pathlib.Path,
        *,
        template: str | pathlib.Path | None = None,
        **context: Any,
    ) -> None:
        path = pathlib.Path(path)
        if path.suffix != ".pdf":
            path = path.with_suffix(".pdf")
        html = self.render(template=template, **context)
        with self._page(html) as page:
            page.pdf(
                path=path,
                format="A4",
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                display_header_footer=False,
                print_background=True,
            )

    def add_builtin_assets(self) -> None:
        super().add_builtin_assets()
        self.add_style(self.print_style.name, self.print_style.read_text())
        self.add_style(self.pagedjs_style.name, self.pagedjs_style.read_text())
        self.add_script(self.pagedjs_script.name, self.pagedjs_script.read_text())

    def extract_toc(self, html: bytes) -> dict[str, int]:
        with self._page(html) as page:
            toc = page.evaluate(
                """
                () => {
                    const toc = {};
                    const headings = document.querySelectorAll('h1[id]');
                    headings.forEach(heading => {
                        let element = heading.closest('.pagedjs_page');
                        if (element) {
                            const number = (
                                element.dataset.pageNumber
                                || element.querySelector('.page-number')?.textContent
                            );
                            if (number && heading.id) {
                                toc[heading.id] = parseInt(number);
                            }
                        }
                    });
                    return toc;
                }
                """
            )
            return toc

    @contextlib.contextmanager
    def _page(self, html: bytes) -> Iterator[Page]:
        with tempfile.NamedTemporaryFile(suffix=".html") as f, sync_playwright() as p:
            f.write(html)
            prefix = f.name.rsplit("/", 1)[0]
            browser = p.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append(f"Page error: {exc}"))
            page.on("requestfailed", lambda req: errors.append(f"Request failed: {req.url}"))

            def route_assets(route, request):
                url = request.url.split("://", 1)[-1]
                path = url[len(prefix) + 1 :]
                if path in self.assets:
                    asset = self.assets[path]
                    route.fulfill(
                        status=200,
                        body=asset.data,
                        headers={"Content-Type": asset.mimetype},
                    )
                else:
                    route.continue_()

            page.route("**/*", route_assets)
            page.goto(f"file://{f.name}")
            try:
                page.wait_for_function("window.status === 'pagedone'", timeout=5000)
                yield page
            except Exception:
                for error in errors:
                    print(error)
                raise
            finally:
                browser.close()
