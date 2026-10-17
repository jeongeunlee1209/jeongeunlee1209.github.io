import os
import sys

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ALLOWED_CHAT_ID", "111")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "_import.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
