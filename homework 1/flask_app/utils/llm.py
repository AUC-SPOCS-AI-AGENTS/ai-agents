
import os
from groq import Groq

DEFAULT_MODEL = "openai/gpt-oss-120b"


def send_message(user_message, system_prompt="You are a helpful assistant."):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return "GROQ_API_KEY is missing. Check your .env file."

    try:
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=1024
        )

        return response.choices[0].message.content

    except Exception as error:
        print(f"Groq error: {error}")
        return f"Could not reach the AI: {error}"
