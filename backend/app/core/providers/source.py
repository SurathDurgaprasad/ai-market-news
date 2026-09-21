from typing import Optional, Dict, Any
import json
from app.core.parser import ArticleData, parse_mock_source
from tests.fixtures.sources import FIXTURES

class TestSourceProvider:
    # Opt out of pytest collection — this is a test-mode provider, not a test class
    __test__ = False
    """
    Deterministic provider for testing ingestion logic without external dependencies.
    Simulates network latency, rate limits (429), server errors (500), and fetching content.
    """
    
    def __init__(self):
        self.call_counts = {}
        
    def fetch(self, source_url: str, fixture_key: str) -> Dict[str, Any]:
        """
        Simulate a network fetch.
        """
        self.call_counts[source_url] = self.call_counts.get(source_url, 0) + 1
        
        # Simulate rate limit
        if "429" in fixture_key:
            return {"status": 429, "error": "Too Many Requests"}
            
        # Simulate server error
        if "500" in fixture_key:
            return {"status": 500, "error": "Internal Server Error"}
            
        # Simulate timeout
        if "timeout" in fixture_key:
            return {"status": 408, "error": "Request Timeout"}
            
        payload = FIXTURES.get(fixture_key)
        if not payload:
            return {"status": 404, "error": "Not Found"}
            
        # Simulate parsing success
        if isinstance(payload, str):
            json_payload = payload
        else:
            json_payload = json.dumps(payload)
            
        parsed = parse_mock_source(json_payload)
        return {"status": 200, "data": parsed}
