import ollama

# Send a message to your local AI model
response = ollama.chat(
    model="qwen3:latest",
    messages=[
        {
            "role": "user",
            "content": "In one sentence, explain what a teaching load is for a university professor.",
        }
    ],
)

# Print the AI's answer
print(response["message"]["content"])
