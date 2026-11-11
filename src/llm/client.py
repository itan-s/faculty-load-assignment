import ollama

#MODEL = "qwen3:latest"  # change here if you use a different model
MODEL = "llama3.2:1b"

def ask_llm(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Send a message to the local model and return its reply as text."""
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        format="json" if json_mode else "",
        options={"temperature": 0},
    )
    return response["message"]["content"]
