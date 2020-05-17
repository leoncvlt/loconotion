import os
import sys
import requests
import shutil
import time
import uuid
import logging
import re
from rich.logging import RichHandler
from rich.progress import Progress
import urllib.parse
import hashlib
import toml
import argparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait 

from bs4 import BeautifulSoup
from pathlib import Path
import cssutils
cssutils.log.setLevel(logging.CRITICAL) # removes warning logs from cssutils

def setup_logger(name):
  rich_handler = RichHandler()
  logger = logging.getLogger(name)
  logger.addHandler(rich_handler)
  logger.setLevel(logging.DEBUG)
  return logger

log = setup_logger("loconotion-logger")

class notion_page_loaded(object):
  """An expectation for checking that a notion page has loaded.
  """
  def __init__(self, url):
    self.url = url

  def __call__(self, driver):
    notion_presence = len(driver.find_elements_by_class_name("notion-presence-container"))
    collection_view_block = len(driver.find_elements_by_class_name("notion-collection_view_page-block"));
    collection_search = len(driver.find_elements_by_class_name("collectionSearch"));
    # embed_ghosts = len(driver.find_elements_by_css_selector("div[embed-ghost]"));
    log.debug(f"Waiting for page content to load (presence container: {notion_presence}, loaders: {loading_spinners} )")
    if (notion_presence and not loading_spinners):
      return True
    else:
      return False

class toggle_block_has_opened(object):
  """An expectation for checking that a notion toggle block has been opened.
  It does so by checking if the div hosting the content has enough children,
  and the abscence of the loading spinner.
  """
  def __init__(self, toggle_block):
    self.toggle_block = toggle_block

  def __call__(self, driver):
    toggle_content = self.toggle_block.find_element_by_css_selector("div:not([style]")
    if (toggle_content):
      content_children = len(toggle_content.find_elements_by_tag_name("div"))
      is_loading = len(self.toggle_block.find_elements_by_class_name("loading-spinner"));
      log.debug(f"Waiting for toggle block to load ({content_children} children so far and {is_loading} loaders)")
      if (content_children > 3 and not is_loading):
        return True
      else:
        return False
    else:
      return False

class Parser():
  def __init__(self, config = {}):
    url = config.get("page", None)
    if not url:
      log.critical("No url specified")
      return

    self.driver = self.init_chromedriver()
    self.config = config

    # get the site name from the config, or make it up by cleaning the target page's slug
    site_name = self.config.get("name", self.get_page_slug(url, extension = False))

    # set the output folder based on the site name, and create it if necessary
    self.dist_folder = Path(config.get("output", Path("dist") / site_name))
    self.dist_folder.mkdir(parents=True, exist_ok=True)
    log.info(f"Setting output path to {self.dist_folder}")

    self.run(url)

  def get_page_config(self, token):
    # starts by grabbing the gobal site configuration table, if exists
    site_config = self.config.get("site", {})

    # check if there's anything wrong with the site config
    if (site_config.get("slug", None)):
      log.error("'slug' parameter has no effect in the [site] table, and should only present in page tables.")
      del site_config['slug']

    # find a table in the configuration file whose key contains the passed token string
    matching_page_config = [value for key, value in self.config.items() if key.lower() in token]
    if (matching_page_config):
      if (len(matching_page_config) > 1):
        log.error(f"multiple matching page config tokens found for {token} in configuration file. Make sure pages urls / slugs are unique")
        return site_config
      else:
        # if found, merge it on top of the global site configuration table
        # log.debug(f"Config table found for page with token {token}")
        return {**site_config, **matching_page_config[0]}
    else:
      # log.debug(f"No config table found for page token {token}, using global site config table")
      return site_config

  def get_page_slug(self, url, extension = True):
    # first check if the url has a custom slug configured in the config file
    custom_slug = self.get_page_config(url).get("slug", None)
    if custom_slug:
      log.debug(f"Custom slug found for url {url}: {custom_slug}")
      return custom_slug.strip("/") + (".html" if extension else "")
    else:
      # if not, clean up the existing slug
      path = urllib.parse.urlparse(url).path.strip("/")
      if ("-" in path and len(path.split("-")) > 1):
        # a standard notion page looks like the-page-title-[uiid]
        # strip the uuid and keep the page title only
        path = "-".join(path.split("-")[:-1]).lower()
      elif ("?" in path):
        # database pages just have an uiid and a query param
        # not much to do here, just get rid of the query param
        path = path.split("?")[0].lower()
      return path + (".html" if extension else "")

  def cache_file(self, url, filename = None):
    if (not filename): filename = url
    destination = self.dist_folder / filename
    if not Path(destination).is_file():
      # Disabling proxy speeds up requests time
      # https://stackoverflow.com/questions/45783655/first-https-request-takes-much-more-time-than-the-rest
      # https://stackoverflow.com/questions/28521535/requests-how-to-disable-bypass-proxy
      session = requests.Session()
      session.trust_env = False
      log.info(f"Downloading '{url}' to '{destination}'")
      response = session.get(url)  
      Path(destination).parent.mkdir(parents=True, exist_ok=True)
      with open(destination, "wb") as f:
        f.write(response.content)
    else:
      log.debug(f"File '{destination}' was already downloaded")
    return destination

  def init_chromedriver(self):
    log.info("Initialising chrome driver")
    chrome_options = Options()  
    chrome_options.add_argument("--headless")  
    chrome_options.add_argument("window-size=1920,1080")
    chrome_options.add_argument("--log-level=3");
    chrome_options.add_argument("--silent");
    chrome_options.add_argument("--disable-logging")
     # removes the 'DevTools listening' log message
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    return webdriver.Chrome(
      executable_path=str(Path.cwd() / "bin" / "chromedriver.exe"), 
      service_log_path=str(Path.cwd() / "webdrive.log"),
      options=chrome_options)

  def parse_page(self, url, processed_pages, index = None):
    # if this is the first page being parse, set it as the index.html
    if (not index):
      index = url;

    log.info(f'Parsing page {url}')
    log.debug(f'Using page config: {self.get_page_config(url)}')
    self.driver.get(url)

    # if ("This content does not exist" in self.driver.page_source):
    #   log.error(f"No content found in {url}. Are you sure the page is set to public?")
    #   return
      
    try:
      # WebDriverWait(self.driver, 10).until(notion_page_loaded())
      WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'notion-presence-container')))
    except TimeoutException as ex:
      log.critical("Timeout waiting for page content to load, or no content found. Are you sure the page is set to public?")
      return

    time.sleep(2)

    # expands all the toggle block in the page to make their content visible
    # we hook up our custom toggle logic afterwards
    def open_toggle_blocks(exclude = []):
      opened_toggles = exclude;
      toggle_blocks = self.driver.find_elements_by_class_name("notion-toggle-block")
      log.debug(f"Opening {len(toggle_blocks)} new toggle blocks in the page")
      for toggle_block in toggle_blocks:
        if (not toggle_block in opened_toggles):
          toggle_button = toggle_block.find_element_by_css_selector("div[role=button]")
          # check if the toggle is already open by the direction of its arrow
          is_toggled = "(180deg)" in (toggle_button.find_element_by_tag_name("svg").get_attribute("style"))
          if (not is_toggled):
            # click on it, then wait until all elements are displayed
            toggle_button.click()
            try:
              WebDriverWait(self.driver, 10).until(toggle_block_has_opened(toggle_block))
            except TimeoutException as ex:
              log.warning("Timeout waiting for toggle block to open")   
            opened_toggles.append(toggle_block) 
      # after all toggles have been opened, check the page again to see if
      # any toggle block had nested toggle blocks inside them
      new_toggle_blocks = self.driver.find_elements_by_class_name("notion-toggle-block")
      if (len(new_toggle_blocks) > len(toggle_blocks)):
        # if so, run the function again
        open_toggle_blocks(opened_toggles)

    open_toggle_blocks()

    # creates soup from the page to start parsing
    soup = BeautifulSoup(self.driver.page_source, "html.parser")

    # process eventual embedded iframes
    for embed in soup.select('div[embed-ghost]'):
      iframe = embed.find('iframe');
      iframe_parent = iframe.parent
      iframe_parent['class'] = iframe_parent.get('class', []) + ['loconotion-iframe-target']
      iframe_parent['loconotion-iframe-src'] = iframe['src']

    # clean up the default notion meta tags
    for tag in ["description", "twitter:card", "twitter:site", "twitter:title", "twitter:description", "twitter:image", "twitter:url", "apple-itunes-app"]:
      unwanted_tag = soup.find("meta", attrs = { "name" : tag})
      if (unwanted_tag): unwanted_tag.decompose();
    for tag in ["og:site_name", "og:type", "og:url", "og:title", "og:description", "og:image"]:
      unwanted_og_tag = soup.find("meta", attrs = { "property" : tag})
      if (unwanted_og_tag): unwanted_og_tag.decompose();

    # set custom meta tags
    custom_meta_tags = self.get_page_config(url).get("meta", [])
    for custom_meta_tag in custom_meta_tags:
      tag = soup.new_tag('meta')
      for attr, value in custom_meta_tag.items():
        tag.attrs[attr] = value
      log.debug(f"Adding meta tag {str(tag)}")
      soup.head.append(tag)

    # process images
    cache_images = True
    for img in soup.findAll('img'):
      if img.has_attr('src'):
        if (cache_images and not 'data:image' in img['src']):
          img_src = img['src']

          # if the path starts with /, it's one of notion's predefined images
          if (img['src'].startswith('/')):
            # notion's images urls are in a weird format, need to sanitize them
            img_src = 'https://www.notion.so' + img['src'].split("notion.so")[-1].replace("notion.so", "").split("?")[0]
            img_src = urllib.parse.unquote(img_src)

          # generate an hashed id for the image filename based the url,
          # so we avoid re-downloading images we have already downloaded,
          # and figure out the filename from the url (I know, just this once)
          img_extension = Path(urllib.parse.urlparse(img_src).path).suffix
          #TODO: unsplash images don't have an extension in the url (they work though)
          img_name = hashlib.sha1(str.encode(img_src)).hexdigest();
          img_file = img_name + img_extension

          self.cache_file(img_src, img_file)
          img['src'] = img_file
        else:
          if (img['src'].startswith('/')):
            img['src'] = "https://www.notion.so" + img['src']

    # process stylesheets
    for link in soup.findAll('link', rel="stylesheet"):
      if link.has_attr('href') and link['href'].startswith('/'):
        # we don't need the vendors stylesheet
        if ("vendors~" in link['href']):
          continue
        css_file = link['href'].strip("/")
        saved_css_file = self.cache_file('https://www.notion.so' + link['href'], css_file)
        with open(saved_css_file, 'rb') as f:
          stylesheet = cssutils.parseString(f.read())
          # open the stylesheet and check for any font-face rule,
          for rule in stylesheet.cssRules:
            if rule.type == cssutils.css.CSSRule.FONT_FACE_RULE:
              # if any are found, download the font file
              font_file = rule.style['src'].split("url(/")[-1].split(") format")[0]
              self.cache_file(f'https://www.notion.so/{font_file}', font_file)
        link['href'] = css_file

    # remove scripts and other tags we don't want / need
    for unwanted in soup.findAll(['script', 'iframe']):
      unwanted.decompose();
    for intercom_div in soup.findAll('div',{'class':'intercom-lightweight-app'}):
      intercom_div.decompose();
    for overlay_div in soup.findAll('div',{'class':'notion-overlay-container'}):
      overlay_div.decompose();
    for vendors_css in soup.find_all("link", href=lambda x: x and 'vendors~' in x):
      vendors_css.decompose();

    # add our custom logic to all toggle blocks
    for toggle_block in soup.findAll('div',{'class':'notion-toggle-block'}):
      toggle_id = uuid.uuid4() 
      toggle_button = toggle_block.select_one('div[role=button]')
      toggle_content = toggle_block.find('div', {'class': None, 'style': ''})
      if (toggle_button and toggle_content):
        # add a custom class to the toggle button and content, plus a custom attribute
        # sharing a unique uiid so we can hook them up with some custom js logic later
        toggle_button['class'] = toggle_block.get('class', []) + ['loconotion-toggle-button']
        toggle_content['class'] = toggle_content.get('class', []) + ['loconotion-toggle-content']
        toggle_content.attrs['loconotion-toggle-id'] = toggle_button.attrs['loconotion-toggle-id'] = toggle_id

    # embed custom google font(s)
    fonts_selectors = {
      "site" : "div:not(.notion-code-block)",
      "navbar": ".notion-topbar div",
      "title" : ".notion-page-block > div, .notion-collection_view_page-block > div",
      "h1" : ".notion-header-block div, notion-page-content > notion-collection_view-block > div:first-child div",
      "h2" : ".notion-sub_header-block div",
      "h3" : ".notion-sub_sub_header-block div",
      "body" : ".notion-app-inner",
      "code" : ".notion-code-block *",
    }
    custom_fonts = self.get_page_config(url).get("fonts", {})
    if (custom_fonts):
      # append a stylesheet importing the google font for each unique font
      unique_custom_fonts = set(custom_fonts.values())
      for font in unique_custom_fonts:
        if (font):
          google_fonts_embed_name = font.replace(" ", "+")
          font_href = f"https://fonts.googleapis.com/css2?family={google_fonts_embed_name}:wght@500;600;700&display=swap"
          custom_font_stylesheet = soup.new_tag("link", rel="stylesheet", href=font_href)
          soup.head.append(custom_font_stylesheet);

      # go through each custom font, and add a css rule overriding the font-family
      # to the font override stylesheet targetting the appropriate selector 
      font_override_stylesheet = soup.new_tag('style', type='text/css')
      for target, custom_font in custom_fonts.items():
        if custom_font and not target == "site":
          log.debug(f"Setting {target} font-family to {custom_font}")
          font_override_stylesheet.append(fonts_selectors[target] + " {font-family:" + custom_font + " !important} ")
      site_font = custom_fonts.get("site", None)
      # process global site font last to more granular settings can override it
      if (site_font):
        log.debug(f"Setting global site font-family to {site_font}"), 
        font_override_stylesheet.append(fonts_selectors["site"] + " {font-family:" + site_font + "} ")
      # finally append the font overrides stylesheets to the page
      soup.head.append(font_override_stylesheet)

    # inject any custom elements to the page
    custom_injects = self.get_page_config(url).get("inject", {})
    def injects_custom_tags(section):
      section_custom_injects = custom_injects.get(section, {})
      for tag, elements in section_custom_injects.items():
        for element in elements:
          injected_tag = soup.new_tag(tag)
          for attr, value in element.items():
            injected_tag[attr] = value
            # if the value refers to a file, copy it to the dist folder
            if (attr.lower() == "href" or attr.lower() == "src"):
              log.debug(f"Copying injected file '{value}'")
              source = (Path.cwd() / value.strip("/"))
              destination = (self.dist_folder / source.name)
              shutil.copyfile(source, destination)
              injected_tag[attr] = source.name
          log.debug(f"Injecting <{section}> tag: {str(injected_tag)}")
          soup.find(section).append(injected_tag)
    injects_custom_tags("head")
    injects_custom_tags("body")

    # inject loconotion's custom stylesheet and script
    custom_css = soup.new_tag("link", rel="stylesheet", href="loconotion.css")
    soup.head.insert(-1, custom_css)
    custom_script = soup.new_tag("script", type="text/javascript", src="loconotion.js")
    soup.body.insert(-1, custom_script)

    # find sub-pages and clean slugs / links
    sub_pages = [];
    for a in soup.findAll('a'):
      if a['href'].startswith('/'):
        sub_page_href = 'https://www.notion.so' + a['href']
        sub_pages.append(sub_page_href)
        a['href'] = self.get_page_slug(sub_page_href) if sub_page_href != index else "index.html"
        log.debug(f"Found link to page {a['href']}")

    # exports the parsed page
    html_str = str(soup)
    html_file = self.get_page_slug(url) if url != index else "index.html"
    log.info(f"Exporting page {url} as {html_file}")
    with open(self.dist_folder / html_file, "wb") as f:
      f.write(html_str.encode('utf-8').strip())
    processed_pages.append(url)

    # parse sub-pages
    for sub_page in sub_pages:
      if not sub_page in processed_pages:
        self.parse_page(sub_page, processed_pages, index)

  def run(self, url):
    processed_pages = []
    self.parse_page(url, processed_pages)

    # copy custom assets to dist folder
    shutil.copyfile("loconotion.css", self.dist_folder / "loconotion.css");
    shutil.copyfile("loconotion.js", self.dist_folder / "loconotion.js");

parser = argparse.ArgumentParser(description='Generate static websites from Notion.so pages')
parser.add_argument('target', help='The config file containing the site properties, or the url of the Notion.so page to generate the site from')
args = parser.parse_args()

if __name__ == '__main__':
  try:
    if urllib.parse.urlparse(args.target).scheme:
      try:
        response = requests.get(args.target)
        if ("notion.so" in args.target):
          log.info("Initialising parser with simple page url")
          Parser({ "page" : args.target })
        else:
          log.critical(f"{args.target} is not a notion.so page")
      except requests.ConnectionError as exception:
        log.critical(f"{args.target} does not seem to be an existing web page")
    else:
      if Path(args.target).is_file():
        with open(args.target) as f:
          parsed_config = toml.loads(f.read())
          log.info("Initialising parser with configuration file")
          Parser(parsed_config)
      else:
        log.critical(f"Config file {args.target} does not exists")
  except FileNotFoundError as e:
    log.critical(f'FileNotFoundError: {e}')
    sys.exit(0)
  except KeyboardInterrupt:
    log.critical('Interrupted by user')
    try:
      sys.exit(0)
    except SystemExit:
      os._exit(0)