import json
import os
from pathlib import Path
from threading import Thread

from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.chrome.options import Options

from django.conf import settings
from .models import Site, MemorySite, Content

options = Options()
options.page_load_strategy = 'normal'
options.headless = True


def scraper(depth: int, url: str, consumer, mem_site: MemorySite):
    browser = webdriver.Chrome(
        executable_path=settings.BASE_DIR / 'chromedriver',
        chrome_options=options,
    )
    directory = settings.BASE_DIR / 'media' / str(consumer.crawl.id)
    scrape_url(browser, consumer, mem_site, depth, 1, url, directory, mem_site)

    mem_site.send_progress(100)


def calc_children(link):
    link.child_url = link.get_attribute('href')
    return link


def scrape_url(browser: webdriver.Chrome, consumer, root: MemorySite, depth, current_depth, url, directory: Path, mem_site: MemorySite):
    if url:
        try:
            browser.set_page_load_timeout(10)
            browser.get(url)
            html_tag = browser.find_element_by_tag_name('html')
            html = html_tag.get_attribute('outerHTML')
            Content.objects.create(site=mem_site.site, content=html)
            filename = directory / f'{mem_site.site.id}.html'
            os.makedirs(f'{os.path.dirname(filename)}/children', exist_ok=True)
            with open(filename, 'w') as f:
                f.write(html)

            if current_depth < depth:
                all_links = list(map(calc_children, html_tag.find_elements_by_tag_name('a')))
                for link in all_links:
                    if not link.child_url:
                        continue
                    child_site = Site.objects.create(crawl=consumer.crawl, url=link.child_url, parent=mem_site.site)
                    children_directory = directory / 'children'
                    child_site = MemorySite(child_site, consumer.send, steps=depth)
                    scrape_url(
                        browser, consumer, root, depth, current_depth + 1,
                        link.child_url, children_directory, child_site
                    )

        except TimeoutException as e:
            print('site timeout: ', e)
        except WebDriverException as e:
            print('web driver exception: ', e)

    root.increment_progress()


def run_engine(data, consumer):
    initial_links, depth = data['initial_links'], data['depth']
    sites = [
        Site.objects.create(crawl=consumer.crawl, url=url, parent=None)
        for url in initial_links
    ]
    data = {'type': 'SET_ID', 'sites': [{site.url: site.id} for site in sites]}
    consumer.send(text_data=json.dumps(data))

    processes = []
    for site in sites:
        mem_site = MemorySite(site, consumer.send, steps=depth)
        process = Thread(target=scraper, args=(depth, site.url, consumer, mem_site))
        process.start()
        processes.append(process)

    for proc in processes:
        proc.join()

    consumer.send(text_data=json.dumps({
        'is_done': True,
        'crawl_id': consumer.crawl.id
    }))
