"""Quick import check for pipeline service availability."""
services = {
    "OpenAILLMService": "from pipecat.services.openai.llm import OpenAILLMService",
    "OpenAITTSService": "from pipecat.services.openai.tts import OpenAITTSService",
    "OpenAISTTService": "from pipecat.services.openai.stt import OpenAISTTService",
    "GroqLLMService":   "from pipecat.services.groq.llm import GroqLLMService",
    "DeepgramSTT":      "from pipecat.services.deepgram.stt import DeepgramSTTService",
}
for name, stmt in services.items():
    try:
        exec(stmt)
        print(f"OK   {name}")
    except ImportError as e:
        print(f"MISS {name}: {e}")
    except Exception as e:
        print(f"ERR  {name}: {e}")
