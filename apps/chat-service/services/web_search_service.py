import os
import asyncio
import logging
from typing import List, Dict, Any
from ddgs import DDGS

# Get logger for this module
logger = logging.getLogger(__name__)

# Configuration
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "10"))
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes")


class WebSearchService:
    def __init__(self):
        self.enabled = WEB_SEARCH_ENABLED
        logger.info(f"WebSearchService initialized - enabled: {self.enabled}")
        logger.info(f"Max results: {WEB_SEARCH_MAX_RESULTS}, timeout: {WEB_SEARCH_TIMEOUT}s")

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Perform web search using DuckDuckGo.
        Returns a list of search results with title, body, and href.
        """
        if not self.enabled:
            logger.info("Web search is disabled")
            return []

        try:
            logger.info(f"Starting web search for query: '{query}'")

            # Run the synchronous search in a thread pool
            def _search_sync():
                with DDGS() as ddgs:
                    results = []
                    search_results = ddgs.text(
                        query,
                        region='fi-fi',  # Finland Finnish locale
                        backend='duckduckgo',  # Explicitly use DuckDuckGo backend
                        max_results=WEB_SEARCH_MAX_RESULTS,
                        safesearch='moderate',
                        timelimit='y'  # Results from past year
                    )
                    for result in search_results:
                        results.append({
                            'title': result.get('title', ''),
                            'body': result.get('body', ''),
                            'href': result.get('href', ''),
                            'snippet': result.get('body', '')[:300] + '...' if len(result.get('body', '')) > 300 else result.get('body', '')
                        })
                    return results

            results = await asyncio.to_thread(_search_sync)
            logger.info(f"Web search for '{query}' returned {len(results)} results")

            logger.info(f"Full web search results: {results}")

            # Log a brief summary of the results
            if results:
                titles = [result['title'][:60] + '...' if len(result['title']) > 60 else result['title'] for result in results[:3]]
                logger.info(f"Top results: {'; '.join(titles)}")

            return results

        except Exception as e:
            logger.error(f"Web search failed for query '{query}': {e}")
            return []

    def format_search_results(self, query: str, results: List[Dict[str, Any]]) -> str:
        """
        Format search results into a readable string for the LLM context.
        Uses letters (A, B, C, ...) instead of numbers for result labels.
        """
        if not results:
            return ""

        formatted = f"[WEBSEARCH] You have access to real-time information via a web search and you ran the following query '{query}' and received the following results:\n\n"
        formatted_parts = []
        for i, result in enumerate(results):
            label = chr(ord('A') + i)
            formatted_parts.append(f"[{label}] {result['title']}: {result['snippet']}")
        formatted += "\n\n".join(formatted_parts)
        return formatted

    def format_search_results_as_refs(self, results: List[Dict[str, Any]]) -> List[str]:
        if not results:
            return []

        search_results_as_references = []
        for i, result in enumerate(results):
            label = chr(ord('A') + i)
            search_results_as_references.append({
                "reference_id": label,
                "type": "website",
                "title": result['title'],
                "source": result['href']
            })
        return search_results_as_references