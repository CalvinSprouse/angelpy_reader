#!/usr/bin/env python3

"""Download entrys from TLA forums."""

# imports
import random
import re
import shutil
import time

from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag, ParseResult

import html2text
import numpy as np
import requests

from bs4 import BeautifulSoup
from rich import print
from tqdm import tqdm


# ## Define Functions
# define a function to parse tla style urls
def parse_tla_url(tla_url: str) -> dict:

    # parse the tla url
    parsed_tla = urlparse(tla_url)


    # extract the page number
    # the default page number will be 1
    page_number = 1

    # create a regular expression for extracting the page number
    # the page number comes at the end of the url of the form
    # page-# where # is any digit page number
    page_number_regex = re.compile(r'page-(\d+)$')

    # extract the page number from parsed_tla.path
    # if none exists default to one
    page_number_match = page_number_regex.search(parsed_tla.path)
    if page_number_match:
        page_number = int(page_number_match.group(1))


    # extract the post id as an integer from the fragment using regular expression
    # the post id comes at the end of the url of the form
    # post-# where # is any digit page number
    post_id_regex = re.compile(r'post-(\d+)$')

    # extract the post id from parsed_tla.fragment
    post_id_match = post_id_regex.search(parsed_tla.fragment)
    post_id = int(post_id_match.group(1))


    # return the page and post as a dict
    return {'page': page_number, 'post': post_id}


# define a function to compose tla style urls
def compose_tla_url(base_url: str, page: int, post: int) -> ParseResult:

    # take the page and posts and turn them into strings
    page_str = f"page-{page}"
    post_str = f"#post-{post}"
    joint_str = f"{page_str}/{post_str}"

    # compose a joined url from urljoin
    joint_url = urljoin(base_url, joint_str)

    # return a parsed joint url
    joint_parse_url = urlparse(joint_url)
    return joint_parse_url


# define a function to get soup from a link
def make_soup(link: str, headers: dict = None, pause_interval: float = None) -> BeautifulSoup:
    """Makes a soup from a link.

    Arguments:
        link -- the link to make the soup from (str).

    Keyword Arguments:
        headers -- the headers to use for the request (default: User-Agent: Mozilla/5.0).

    Returns:
        soup -- the soup from the link (BeautifulSoup).
    """

    # create default headers if none were passed
    if headers is None:
        headers = {"User-Agent": "Mozilla/5.0"}

    # if no pause interval was passed pause for a random interval to avoid
    # overloading websites
    if pause_interval is None: pause_interval = random.uniform(0.5, 1.5)

    time.sleep(pause_interval)

    # create a requests session to handle webpage data
    session = requests.Session()

    # get a response from the main page
    response = session.get(link, headers=headers)

    # check the response code and raise an error if not good
    if response.status_code != 200:
        raise Exception(f"Bad response code: {response.status_code}")

    # parse the soup
    soup = BeautifulSoup(response.content, "html.parser")

    # return the soup
    return soup


# define a function to parse a threadmark page
def parse_threadmark_page(threadmark_link: str) -> np.array:
    """Parse a threadmark page (table of contents) and return chapter links.

    Arguments:
        threadmark_link -- A link to the threadmark page, ends in /threadmarks

    Returns:
        A dictionary with keys
        "href": link to chapter,
        "post": the post number,
        "title": the text accompanying the link
    """

    # define a link to a threadmark page
    # threadmark_link = str(tla_links[0].get("href")) + "threadmarks"
    # print(f"Threadmark: '{threadmark_link}'")

    # parse out the link
    # parsed_link = urlparse(threadmark_link)

    # get the soup of a threadmark page
    thread_soup = make_soup(threadmark_link)

    # get the threadmark containers
    # each container has a link to a threadmark
    threadmark_containers = thread_soup.find_all(attrs={"class": "structItem--threadmark"})

    # extract all the links from threadmark containers
    # the first link is from the actual link and has the text, the second has the date
    # so take only the first
    thread_links = [l.find_all("a")[0] for l in threadmark_containers]

    # clean the thread links
    # first parse into a list of lists (parsed link, link label)
    # clean_thread_links = [(urlparse(l.get("href")), l.get_text().strip()) for l in thread_links]

    # compose full links from the urlparse with the base scheme and netloc
    # save as a list of tuples of the form (link, post code, link label)
    # use url join from urlparse?
    parsed_thread_links = np.array(
        [(
            (parsed_url := parse_tla_url(l.get("href")))["page"],
            parsed_url["post"],
            l.get_text()
        ) for l in thread_links],
        dtype=[
            ("page", np.int32),
            ("post", np.int64),
            ("title", np.object_)
        ]
        )

    # return the thread links
    return parsed_thread_links


# define a function to parse a chapter from above methods
def parse_entry(base_url: str, page: int, post: int) -> str:

    # compose the entry url
    entry_url = compose_tla_url(base_url, page, post)

    # get the soup
    entry_soup = make_soup(entry_url.geturl())

    # get the first div element with data-lb-id=post-id
    post_element = entry_soup.find("div", {"data-lb-id": entry_url.fragment})

    # go in one layer and find the class=bbWrapper tag
    post_wrapper = post_element.find("div", class_="bbWrapper")

    # unfortunately due to mixed formatting I think it just has to be converted to raw text
    entry_raw_text = str(post_wrapper)

    # pass throught the html to text parser and fix some issues with '_'
    # parse using html2text
    html_parser = html2text.HTML2Text()
    entry_text = html_parser.handle(entry_raw_text)

    # if a number of asterix are seperated from another group of asterix by nothing but blank space
    # characters remove the blank space characters and the asterix
    # example **text** **more text** would become **textmore text**
    # but there might be any number of asterix that need to be removed
    # this is done to make the regex for finding the entry titles easier
    entry_text = re.sub(r"\*\*\s+\*\*", " ", entry_text)
    return entry_text


# define the main function to download TLA entrys
def main():
    # ## Extract Info on Each Chapter
    # scrape the links from the main webpage

    # the links will have associated text The Last Angel and come from this page
    main_page = r"https://proximalflame.com/index-2/"

    # get a response from the main page and extract the html
    soup = make_soup(main_page)

    # extract all links from the main page
    links = list(soup.find_all("a"))

    # get only links with text The Last Angel
    # these are the links to the main stories
    # appending threadmarks to the end of these links gives a table of contents of sorts
    # this works for now but is a little messy
    tla_links = [
        {
            "href": (href := urldefrag(l.get("href"))[0]),
            "title": l.get_text().strip(),
            "entrys": parse_threadmark_page(urljoin(href, "threadmarks"))
        }
        for l in links if "the last angel" in l.get_text().strip().lower()]


    # iterate over each selection in tla_links
    # define a save location for all output
    output_dir = Path(".output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # each selection is a thread
    for thread in tla_links:
        # define a location for the thread
        thread_dir = output_dir / thread['title'].lower().replace(" ", "_").replace(":", "-")
        thread_dir.mkdir(parents=True, exist_ok=True)

        # iterate over each entry in the thread
        for i, entry in enumerate(tqdm(
                thread["entrys"],
                desc=f"Parsing Thread '{thread['title']}'",
                ascii=True,
                leave=True,
                position=0)):

            # define the save location of the entry
            entry_file = thread_dir / f"{entry[2]}.txt"

            # check if the entry exists, if it does don't redownload
            if entry_file.exists(): continue

            # run parse entry because entry does not exist
            entry_text = parse_entry(thread['href'], entry[0], entry[1])

            # save the entry text to a file
            with open(entry_file, "w", encoding="utf-8") as f: f.write(entry_text)


# run the main function
if __name__ == "__main__":
    main()
