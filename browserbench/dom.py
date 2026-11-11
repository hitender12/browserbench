"""HTML -> observation snapshot parser (stdlib html.parser).

Turns a served page into the structured observation an agent sees:
page title, visible text, links (text + href) and forms (action, method,
fields, submit buttons). This is the DOM snapshot recorded in traces.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.text_parts: list[str] = []
        self.links: list[dict] = []
        self.forms: list[dict] = []
        self._current_link: dict | None = None
        self._current_form: dict | None = None
        self._in_button = False
        self._button_text = ""
        self._in_option = False
        self._current_select: dict | None = None
        self._skip = False  # inside <script> or <style>

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self._skip = True
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a" and "href" in attrs:
            self._current_link = {"text": "", "href": attrs["href"]}
        elif tag == "form":
            self._current_form = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "get").lower(),
                "fields": [],
                "submit": None,
            }
        elif tag == "select" and self._current_form is not None:
            field = {
                "name": attrs.get("name", ""),
                "type": "select",
                "options": [],
                "value": attrs.get("value", ""),
            }
            self._current_form["fields"].append(field)
            self._current_select = field
        elif tag == "option" and self._current_select is not None:
            self._in_option = True
            if "value" in attrs:
                self._current_select["options"].append(attrs["value"])
        elif tag == "input" and self._current_form is not None:
            itype = attrs.get("type", "text").lower()
            if itype == "submit":
                self._current_form["submit"] = attrs.get("value", "Submit")
            elif itype == "hidden":
                self._current_form["fields"].append(
                    {"name": attrs.get("name", ""), "type": "hidden",
                     "value": attrs.get("value", "")}
                )
            else:
                self._current_form["fields"].append(
                    {"name": attrs.get("name", ""), "type": itype,
                     "value": attrs.get("value", "")}
                )
        elif tag == "textarea" and self._current_form is not None:
            self._current_form["fields"].append(
                {"name": attrs.get("name", ""), "type": "textarea", "value": ""}
            )
        elif tag == "button" and self._current_form is not None:
            self._in_button = True
            self._button_text = ""
            self._current_form.setdefault("_button_type", attrs.get("type", "submit"))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._current_link is not None:
            link = self._current_link
            link["text"] = " ".join(link["text"].split())
            if link["text"]:
                self.links.append(link)
            self._current_link = None
        elif tag == "form" and self._current_form is not None:
            self._current_form.pop("_button_type", None)
            if self._current_form["submit"] is None:
                self._current_form["submit"] = "Submit"
            self.forms.append(self._current_form)
            self._current_form = None
        elif tag == "select":
            self._current_select = None
        elif tag == "option":
            self._in_option = False
        elif tag == "button" and self._current_form is not None:
            self._in_button = False
            text = " ".join(self._button_text.split())
            if text:
                self._current_form["submit"] = text

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._current_link is not None:
            self._current_link["text"] += data
        if self._in_button:
            self._button_text += data
        text = data.strip()
        if text:
            self.text_parts.append(text)


def parse_html(html: str, url: str) -> dict:
    """Parse an HTML page into an observation snapshot."""
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return {
        "url": url,
        "title": " ".join(parser.title.split()),
        "text": " ".join(parser.text_parts),
        "links": parser.links,
        "forms": parser.forms,
    }
