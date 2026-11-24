
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient


# Load environment variables
env_path = (
    Path(__file__).resolve().parent.parent
    / "assistant_agent"
    / ".env"
)

load_dotenv(env_path)


# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI")

if not MONGODB_URI:
    raise ValueError("MONGODB_URI is missing!")

client = MongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=5000
)

# Database and collection
db = client["personal_assistant"]

tasks_collection = db["tasks"]


def test_connection():
    try:
        client.admin.command("ping")

        tasks_collection.create_index(
            "id",
            unique=True
        )

        tasks_collection.create_index("date")

        return {
            "status": "success",
            "message": "MongoDB connected successfully!"
        }

    except Exception as error:
        return {
            "status": "error",
            "message": str(error)
        }
