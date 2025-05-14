from __future__ import annotations

import enum
import mimetypes
import pathlib
import re
from typing import ClassVar, Pattern

import yaml
from pydantic import BaseModel, Field


class Format(str, enum.Enum):
    web = "web"
    print = "print"
    ebook = "ebook"

    @classmethod
    def match(cls, name: str) -> tuple[str, list[Format] | None]:
        formats: list[Format] = []
        for format in cls:
            prefix = f"{format.value}_"
            if name.startswith(prefix):
                formats.append(format)
                name = name.removeprefix(prefix)
        return name, formats or None


class AssetType(str, enum.Enum):
    image = "image"
    font = "font"
    style = "style"
    script = "script"
    file = "file"

    @property
    def directory_name(self) -> str:
        return {
            self.image: "images/",
            self.font: "fonts/",
            self.style: "styles/",
            self.script: "scripts/",
            self.file: "files/",
        }[self]


class ExtensionType(str, enum.Enum):
    template = "template"
    module = "module"


class Book(BaseModel):

    metadata_filename: ClassVar[str] = "book.yaml"
    chapters_directory_name: ClassVar[str] = "chapters"
    assets_directory_name: ClassVar[str] = "assets"
    extensions_directory_name: ClassVar[str] = "extensions"

    title: str
    authors: list[str] = Field(default_factory=list)
    identifier: str | None = None
    language_code: str = "en"
    default_code_language: str = "python"
    chapters: list[Chapter] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    extensions: list[Extension] = Field(default_factory=list)
    path: pathlib.Path | None = None

    def __repr__(self) -> str:
        return f"<book {self.title!r}>"

    @classmethod
    def from_directory(
        cls,
        path: str | pathlib.Path,
        *,
        metadata_filename: str | None = None,
        chapters_directory_name: str | None = None,
        assets_directory_name: str | None = None,
        extensions_directory_name: str | None = None,
    ) -> Book:
        if metadata_filename is None:
            metadata_filename = cls.metadata_filename
        if chapters_directory_name is None:
            chapters_directory_name = cls.chapters_directory_name
        if assets_directory_name is None:
            assets_directory_name = cls.assets_directory_name
        if extensions_directory_name is None:
            extensions_directory_name = cls.extensions_directory_name
        path = pathlib.Path(path)
        cls._assert_directory(path)
        metadata_path = path / metadata_filename
        metadata = yaml.safe_load(metadata_path.read_text())
        book = Book(**metadata, path=path)
        book.collect_chapters(path / chapters_directory_name)
        assets_path = path / assets_directory_name
        if assets_path.exists():
            book.collect_assets(assets_path)
        extensions_path = path / extensions_directory_name
        if extensions_path.exists():
            book.collect_extensions(extensions_path)
        return book

    def collect_chapters(self, path: pathlib.Path) -> None:
        path = pathlib.Path(path)
        self._assert_directory(path)
        for chapter_path in path.iterdir():
            if chapter_path.is_dir():
                continue
            chapter = Chapter.from_file(chapter_path)
            self.chapters.append(chapter)
        self.chapters.sort(key=lambda chapter: chapter.number)

    def collect_assets(self, path: pathlib.Path) -> None:
        path = pathlib.Path(path)
        self._assert_directory(path)
        for asset_path in path.rglob("*"):
            if asset_path.is_dir():
                continue
            asset = Asset.from_file(asset_path)

            self.assets.append(asset)

    def collect_extensions(self, path: pathlib.Path) -> None:
        path = pathlib.Path(path)
        self._assert_directory(path)
        for extension_path in path.rglob("*"):
            if extension_path.is_dir():
                continue
            extension = Extension.from_file(extension_path)
            self.extensions.append(extension)

    @classmethod
    def _assert_directory(cls, path: pathlib.Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"directory {path} does not exist")
        if not path.is_dir():
            raise NotADirectoryError(f"{path} is not a directory")


class Chapter(BaseModel):

    chapter_name_regex: ClassVar[Pattern] = re.compile(r"^(\d+)-(.*)$")

    id: str
    number: int
    text: str
    title: str | None = None
    sections: dict[str, Section] = Field(default_factory=dict)
    path: pathlib.Path | None = None

    def __repr__(self) -> str:
        return f"<chapter #{self.number}: {self.id}>"

    @classmethod
    def from_file(cls, path: pathlib.Path) -> Chapter:
        path = pathlib.Path(path)
        match = cls.chapter_name_regex.match(path.stem)
        if not match:
            raise ValueError(f"{path} is not a valid chapter path (expected '<number>-<id>.vyn')")
        number, id = match.groups()
        number = int(number)
        text = path.read_text()
        return cls(id=id, number=number, text=text, path=path)


class Section(BaseModel):
    id: str
    title: str


class Asset(BaseModel):

    mimetypes: ClassVar[dict[str, AssetType]] = {
        "image/png": AssetType.image,
        "image/jpeg": AssetType.image,
        "image/gif": AssetType.image,
        "image/svg+xml": AssetType.image,
        "font/ttf": AssetType.font,
        "font/otf": AssetType.font,
        "font/woff": AssetType.font,
        "font/woff2": AssetType.font,
        "text/css": AssetType.style,
        "text/javascript": AssetType.script,
    }

    name: str
    type: AssetType
    mimetype: str
    data: bytes
    formats: list[Format] | None = None
    path: pathlib.Path | None = None

    def __repr__(self) -> str:
        return f"<{self.type.value} {self.name!r}>"

    @classmethod
    def from_file(cls, path: pathlib.Path) -> Asset:
        path = pathlib.Path(path)
        mimetype, _ = mimetypes.guess_type(path.name)
        if mimetype is None:
            raise ValueError(f"{path.name} does not match any mimetype")
        if mimetype not in cls.mimetypes:
            raise ValueError(
                f"{path.name} mimetype is not supported (supported mimetypes are {', '.join(cls.mimetypes)})"
            )
        asset_type = cls.mimetypes[mimetype]
        data = path.read_bytes()
        name, formats = Format.match(path.name)
        return cls(
            name=name,
            type=asset_type,
            mimetype=mimetype,
            data=data,
            formats=formats,
            path=path,
        )

    @property
    def url(self) -> str:
        return f"{self.type.directory_name}{self.name}"


class Extension(BaseModel):

    name: str
    type: ExtensionType
    text: str
    formats: list[Format] | None = None
    path: pathlib.Path | None = None

    def __repr__(self) -> str:
        return f"<extension {self.name!r}>"

    @classmethod
    def from_file(cls, path: pathlib.Path) -> Extension:
        path = pathlib.Path(path)
        if path.suffix == ".py":
            extension_type = ExtensionType.module
        else:
            extension_type = ExtensionType.template
        name, formats = Format.match(path.stem)
        text = path.read_text()
        return cls(
            name=name,
            type=extension_type,
            text=text,
            formats=formats,
            path=path,
        )


class Font(BaseModel):
    url: str
    type: str
    family: str
    weight: int
    style: str
