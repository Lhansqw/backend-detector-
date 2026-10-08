"""Revisión de archivos críticos con Claude."""
import json, os
import sys

MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
SYSTEM = (
    "Eres un revisor de código senior que evalúa deuda técnica. Responde SOLO con un objeto JSON, "
    "sin texto adicional ni markdown, en español, con esta forma: "
    '{"summary": str, "issues": [{"type": str, "description": str}], "refactor": str}. '
    "Los tipos válidos son: abstraccion, nombres, acoplamiento, duplicacion, complejidad, tests, otro. "
    "Máximo 5 issues, concretos y específicos del código recibido."
)


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def review_file(path: str, code: str, metrics: dict) -> dict:
    try:
        try:
            from groq import Groq
        except ImportError:
            raise RuntimeError("Groq SDK not installed. Run 'pip install groq' and ensure it's in requirements.")

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Archivo: {path}\nMétricas: {json.dumps(metrics)}\n\n```\n{code[:12000]}\n```"},
            ],
            max_tokens=1200,
        )
        # Groq returns a list of choices with a message
        if not response.choices:
            return {"error": "No response from Groq"}
        text = response.choices[0].message.content.strip()
        # Expect JSON payload
        text = text.removeprefix("```json").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:  # la IA nunca debe tumbar el análisis completo
        return {"error": f"No se pudo revisar con IA: {type(e).__name__}"}
