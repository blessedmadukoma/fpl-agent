from pathlib import Path

from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"

# The js-default preset escapes raw HTML and refuses javascript: and data: links.
_markdown = MarkdownIt("js-default")


def markdown(text: str) -> Markup:
    return Markup(_markdown.render(text))


templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["markdown"] = markdown
# Keep accented player names readable and tool fields in the order the tool returned them.
templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}
