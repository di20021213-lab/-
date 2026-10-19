"""
Поддельный сервер Ollama для проверки помощника без настоящей нейросети.

На просьбу пользователя он по очереди «просит» помощника:
  1) выполнить команду, которая печатает ok-5 (2+3 считает сама оболочка);
  2) записать файл smoke_test_output.txt;
  3) затем отвечает текстом DONE.

Запуск: python tests/fake_ollama.py ПОРТ
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "qwen2.5:7b"


def tool_call(name, arguments):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self.reply({"models": [{"name": MODEL, "model": MODEL}]})
        else:
            self.reply({"error": "not found"}, 404)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/chat":
            return self.reply({"error": "not found"}, 404)
        messages = request["messages"]
        powershell = "PowerShell" in messages[0]["content"]
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        tool_results = [m for m in messages[last_user:] if m["role"] == "tool"]

        if len(tool_results) == 0:
            command = 'Write-Output ("ok-" + (2+3))' if powershell else 'echo "ok-$((2+3))"'
            message = tool_call("run_command", {"command": command, "explanation": "test"})
        elif len(tool_results) == 1:
            message = tool_call("write_file", {"path": "smoke_test_output.txt",
                                               "content": "smoke-file\nстрока по-русски\n"})
        else:
            message = {"role": "assistant", "content": "DONE"}
        self.reply({"model": MODEL, "message": message, "done": True})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
