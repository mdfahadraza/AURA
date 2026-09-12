import requests
from bs4 import BeautifulSoup


def scrape(url):
    """Scrape a URL. Returns error message if offline / unreachable."""
    try:
        r = requests.get(url, timeout=5)
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text()[:1000]
    except requests.ConnectionError:
        return "[Offline] Cannot reach the internet. Web scraping is unavailable."
    except requests.Timeout:
        return "[Timeout] The request timed out. Check your connection."
    except Exception as e:
        return f"[Error] {e}"
