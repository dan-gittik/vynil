import argparse
import pathlib

from .extract_fonts import extract_fonts
from .model import Book, Format
from .renderer import Renderer

ROOT = pathlib.Path(__file__).parent
DEFAULT_PORT = 8000

formats = [format.value for format in Format]


def cli(argv: list[str] | None = None) -> None:

    parser = argparse.ArgumentParser(description="Vynil book generation tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="generate a book")
    generate_parser.add_argument("format", help="rendering format", choices=formats)
    generate_parser.add_argument("path", help="book directory")
    generate_parser.add_argument("-o", "--output", help="output path")

    serve_parser = subparsers.add_parser("serve", help="serve a book")
    serve_parser.add_argument("format", help="rendering format", choices=formats)
    serve_parser.add_argument("path", help="book directory")
    serve_parser.add_argument("-p", "--port", default=DEFAULT_PORT, help="port to serve on")

    extract_parser = subparsers.add_parser("extract", help="extract static fonts from a variable font")
    extract_parser.add_argument("path", help="variable font path")

    args = parser.parse_args(argv)

    match args.command:

        case "generate":
            book = Book.from_directory(args.path)
            if args.output:
                output = pathlib.Path(args.output)
            else:
                output = pathlib.Path(args.path) / "output"
            renderer = Renderer.create(args.format, book)
            renderer.generate(output)

        case "serve":
            book = Book.from_directory(args.path)
            renderer = Renderer.create(args.format, book)
            renderer.serve(args.port)

        case "extract":
            extract_fonts(args.path)
