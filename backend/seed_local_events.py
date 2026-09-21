"""Load fixture-derived events into the local SQLite DB for UI inspection."""
import os
import sys

os.environ["TEST_MODE"] = "true"
os.environ["TESTING"] = "1"

sys.path.insert(0, os.path.dirname(__file__))

from app.db.session import SessionLocal, engine
from app.db.base_class import Base
from app.models.source import Source
from app.core.pipeline import IntelligencePipeline
from app.core.providers.source import TestSourceProvider

KEYS = [
    "normal_1",
    "normal_2",
    "adversarial_1_official",
    "adversarial_2_unrelated_announcement",
    "adversarial_5_gemini_ultra",
    "adversarial_5_gemini_pro",
    "minutes_apart_model",
]


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        source = Source(name="OpenAI Blog", url="https://openai.com/blog/rss", type="rss", tier="primary")
        db.add(source)
        db.commit()
        pipeline = IntelligencePipeline(db)
        provider = TestSourceProvider()
        created = 0
        for key in KEYS:
            data = provider.fetch("seed", key)["data"]
            event = pipeline.process_article(data, source.id)
            if event:
                created += 1
                print(f"  event: {event.headline} score={event.importance_score} time={event.event_time}")
        print(f"Seeded {created} events")
    finally:
        db.close()


if __name__ == "__main__":
    main()
