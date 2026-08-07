from dotenv import load_dotenv
import os

load_dotenv()

BLAND_API_KEY = os.getenv("BLAND_API_KEY")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./staykaro.db"
)