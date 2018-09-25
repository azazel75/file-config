# Copyright (c) 2018 Stephen Bunn <stephen@bunn.io>
# MIT License <https://opensource.org/licenses/MIT>

from ._common import BaseHandler


class JSONHandler(BaseHandler):

    name = "json"
    packages = ("ujson", "json",)

    def on_json_dumps(self, json, dictionary: dict) -> str:
        return json.dumps(dictionary)

    def on_json_loads(self, json, content: str) -> dict:
        return json.loads(content)

    def on_ujson_dumps(self, ujson, dictionary: dict) -> str:
        return ujson.dumps(dictionary)

    def on_ujson_loads(self, ujson, content: str) -> dict:
        return ujson.loads(content)