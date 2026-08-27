"""
Puente mínimo entre un LLM local servido por Ollama y el servidor mcp-pionex.

Arranca el servidor MCP por stdio, expone sus 56 tools al modelo local vía la
API de tool-calling de Ollama, y ejecuta el bucle agéntico (modelo → tool →
resultado → modelo) respetando las guardas del servidor: si el modelo intenta
algo bloqueado, recibe el mensaje correctivo literal del servidor.

Requisitos:
    - Ollama corriendo en local (https://ollama.com) con un modelo que soporte
      tool-calling, p. ej.:  ollama pull qwen3
    - pip install mcp requests   (o `uv run examples/ollama_bridge.py` desde
      este repo, que ya trae ambos)

Uso:
    python examples/ollama_bridge.py "¿a cuánto está el BTC?"
    OLLAMA_MODEL=llama3.1 python examples/ollama_bridge.py "lista pares con DOGE"
"""

import asyncio
import json
import os
import sys

import requests

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3")
MAX_TOOL_ROUNDS = 8

SERVER = StdioServerParameters(
    command="uv",
    args=["--directory", os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
          "run", "mcp-pionex"],
    # Las credenciales y puertas se heredan del entorno actual; el puente no
    # las toca — la postura de seguridad sigue siendo cosa del operador.
    env=os.environ.copy(),
)


def to_ollama_tools(mcp_tools) -> list:
    """Convierte las tools MCP al formato de tools de Ollama (estilo OpenAI)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_tools
    ]


def chat(messages: list, tools: list) -> dict:
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages,
              "tools": tools, "stream": False},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["message"]


async def main() -> None:
    question = " ".join(sys.argv[1:]) or "¿Qué herramientas tienes y cuál es el estado del servidor?"

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools_result = await session.list_tools()
            tools = to_ollama_tools(tools_result.tools)
            print(f"[puente] {len(tools)} tools MCP expuestas a {OLLAMA_MODEL}\n")

            messages = [
                # Las instructions del servidor (reglas anti-alucinación) van
                # como system prompt del modelo local, igual que haría Claude.
                {"role": "system", "content": init.instructions or ""},
                {"role": "user", "content": question},
            ]

            for _ in range(MAX_TOOL_ROUNDS):
                message = chat(messages, tools)
                messages.append(message)

                calls = message.get("tool_calls") or []
                if not calls:
                    print(message.get("content", ""))
                    return

                for call in calls:
                    name = call["function"]["name"]
                    args = call["function"].get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    print(f"[tool] {name}({json.dumps(args, ensure_ascii=False)})")
                    result = await session.call_tool(name, args)
                    text = "\n".join(
                        c.text for c in result.content if getattr(c, "text", None)
                    )
                    print(f"       -> {text[:200]}{'…' if len(text) > 200 else ''}")
                    messages.append({"role": "tool", "content": text, "tool_name": name})

            print("[puente] límite de rondas de tools alcanzado")


if __name__ == "__main__":
    asyncio.run(main())
