import pathlib
from typing import Any, ClassVar

from ..model import Format
from ..renderer import Renderer

ROOT = pathlib.Path(__file__).parent


class Web(Renderer):

    format: ClassVar[Format] = Format.web
    template: ClassVar[pathlib.Path] = ROOT / "web.html"
    web_style: ClassVar[pathlib.Path] = ROOT / "web.css"
    web_script: ClassVar[pathlib.Path] = ROOT / "web.js"

    def add_builtin_assets(self) -> None:
        self.add_style(self.web_style.name, self.web_style.read_text())
        self.add_script(self.web_script.name, self.web_script.read_text())

    def generate(
        self,
        path: str | pathlib.Path,
        *,
        template: str | pathlib.Path | None = None,
        **context: Any,
    ) -> None:
        path = pathlib.Path(path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        html = self.render(template, **context)
        (path / "index.html").write_bytes(html)
        for asset_url, asset in self.assets.items():
            asset_path = path / asset_url
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(asset.data)
