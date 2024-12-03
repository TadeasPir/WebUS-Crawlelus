import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
from datetime import datetime
import re
import time
import logging
import os


class NewsCrawler:
    def __init__(self, start_urls, max_pages, output_dir='articles'):
        self.start_urls = start_urls
        self.visited_urls = set()
        self.queue = set(start_urls)
        self.max_pages = max_pages

        # Příprava adresáře pro ukládání
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        # Konfigurace logování
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s: %(message)s',
            filename='crawler.log'
        )

        # Soubor pro ukládání článků
        self.articles_file = os.path.join(self.output_dir, 'articles.json')
        self.articles = []

    def is_valid_article_url(self, url):
        """Filtrování relevantních URL pro články"""
        valid_domains = ['novinky.cz', 'idnes.cz', 'ctk.cz']
        parsed_url = urlparse(url)

        # Kontrola domény
        domain_match = any(domain in parsed_url.netloc for domain in valid_domains)

        # Vyloučení obrázků, videí, souborů
        file_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.mp4']
        is_file = any(url.lower().endswith(ext) for ext in file_extensions)

        # Regulární výraz pro identifikaci článků
        article_patterns = {
            'novinky.cz': r'/clanek/',
            'idnes.cz': r'/zpravy/',
            'ctk.cz': r'/clanek/'
        }

        is_article = any(
            re.search(pattern, url)
            for site, pattern in article_patterns.items()
            if site in parsed_url.netloc
        )

        return domain_match and is_article and not is_file

    def extract_article_data(self, url, soup):
        """Extrakce dat z novinového článku"""
        article_data = {
            'url': url,
            'title': self.extract_title(soup),
            'category': self.extract_category(soup),
            'comments_count': self.extract_comments_count(soup),
            'images_count': len(soup.find_all('img')),
            'content': self.extract_content(soup),
            'created_at': self.extract_date(soup),
            'source_website': urlparse(url).netloc
        }
        return article_data

    def extract_title(self, soup):
        """Extrakce nadpisu podle běžných HTML struktur"""
        title_selectors = [
            'h1.article-title',
            'h1.title',
            'h1',
            'title'
        ]

        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                return title_elem.get_text(strip=True)
        return "Nepodařilo se najít nadpis"

    def extract_category(self, soup):
        """Extrakce kategorie"""
        category_selectors = [
            'span.category',
            'div.rubrika',
            'meta[property="article:section"]'
        ]

        for selector in category_selectors:
            category_elem = soup.select_one(selector)
            if category_elem:
                return category_elem.get('content') or category_elem.get_text(strip=True)
        return "Kategorie nenalezena"

    def extract_comments_count(self, soup):
        """Extrakce počtu komentářů"""
        comments_selectors = [
            'span.comments-count',
            'div.comments-count',
            'meta[itemprop="commentCount"]'
        ]

        for selector in comments_selectors:
            comments_elem = soup.select_one(selector)
            if comments_elem:
                try:
                    return int(re.sub(r'\D', '', comments_elem.get('content', comments_elem.get_text(strip=True))))
                except (ValueError, TypeError):
                    pass
        return 0

    def extract_content(self, soup):
        """Extrakce textového obsahu článku"""
        content_selectors = [
            'div.article-content',
            'div.content',
            'article',
            'div.text'
        ]

        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                return content_elem.get_text(separator=' ', strip=True)
        return "Obsah nenalezen"

    def extract_date(self, soup):
        """Extrakce data publikace"""
        date_selectors = [
            'meta[property="article:published_time"]',
            'time[datetime]',
            'meta[name="date"]'
        ]

        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                date_str = date_elem.get('content') or date_elem.get('datetime')
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).isoformat()
                except (ValueError, TypeError):
                    pass

        return datetime.now().isoformat()

    def save_article(self, article_data):
        """Uložení článku do JSON souboru"""
        # Kontrola duplicit pomocí URL
        if not any(article['url'] == article_data['url'] for article in self.articles):
            self.articles.append(article_data)
            logging.info(f"Uložen článek: {article_data['url']}")

            # Průběžné ukládání po každých 50 článcích
            if len(self.articles) % 50 == 0:
                self.save_json()

    def save_json(self):
        """Uložení aktuálních článků do JSON souboru"""
        try:
            with open(self.articles_file, 'r+', encoding='utf-8') as f:
                json.dump(self.articles, f, ensure_ascii=False, indent=2)
            logging.info(f"Uloženo {len(self.articles)} článků do {self.articles_file}")
        except Exception as e:
            logging.error(f"Chyba při ukládání JSON: {e}")

    def extract_links(self, soup, base_url):
        """Extrakce odkazů z HTML"""
        links = set()
        for link in soup.find_all('a', href=True):
            absolute_url = urljoin(base_url, link['href'])
            if self.is_valid_article_url(absolute_url):
                links.add(absolute_url)
        return links

    def crawl(self):
        """Hlavní crawlovací smyčka"""
        try:
            while self.queue and len(self.visited_urls) < self.max_pages:
                url = self.queue.pop()

                if url in self.visited_urls:
                    continue

                try:
                    response = requests.get(url, timeout=10)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Extrakce a uložení dat článku
                    article_data = self.extract_article_data(url, soup)
                    self.save_article(article_data)

                    # Přidání nových odkazů do fronty
                    new_links = self.extract_links(soup, url)
                    self.queue.update(new_links - self.visited_urls)

                    self.visited_urls.add(url)

                    time.sleep(0.01)  # Omezení rychlosti requestů

                except requests.RequestException as e:
                    logging.error(f"Chyba při crawlování {url}: {e}")

        finally:
            # Konečné uložení všech sesbíraných článků
            self.save_json()


def main():
    start_urls = [
        'https://www.novinky.cz/',
        'https://www.idnes.cz/',
        'https://www.ctk.cz/'
    ]

    crawler = NewsCrawler(start_urls, max_pages=500000)
    try:
        crawler.crawl()
        print("Crawler running")
    except KeyboardInterrupt:
        logging.info("Crawler přerušen uživatelem.")


if __name__ == "__main__":
    main()