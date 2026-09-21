import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.fetcher import fetch_url
from app.core.parser import parse_rss_feed

def main():
    print("Validating Real-Source Ingestion & Thumbnail Extraction...\n")
    
    # We will test a few common AI-related feeds that typically have standard RSS/Atom structures
    # and contain images (media:content, enclosures, etc.)
    
    feeds_to_test = [
        "https://news.ycombinator.com/rss",
        "https://medium.com/feed/tag/artificial-intelligence"
    ]
    
    for url in feeds_to_test:
        print(f"Testing Feed: {url}")
        try:
            response = fetch_url(url)
            content = response.text
            print(f"Successfully fetched {len(content)} bytes.")
            
            articles = parse_rss_feed(content)
            print(f"Parsed {len(articles)} articles.")
            
            if not articles:
                print("No articles parsed. Feed might be empty or unsupported format.\n")
                continue
                
            # Print the first 2 articles to validate extraction
            for idx, article in enumerate(articles[:2]):
                print(f"  Article {idx+1}:")
                print(f"    Title: {article.title}")
                print(f"    URL: {article.url}")
                print(f"    Published: {article.published_at}")
                print(f"    Thumbnail/Image URL: {article.image_url}")
                print(f"    Content Excerpt: {article.content[:100]}...\n")
                
        except Exception as e:
            print(f"Failed to fetch or parse {url}. Error: {e}\n")

if __name__ == "__main__":
    main()
