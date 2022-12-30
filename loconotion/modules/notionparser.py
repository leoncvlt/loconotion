import glob
import hashlib
import logging
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

log = logging.getLogger(f"loconotion.{__name__}")

try:
    import chromedriver_autoinstaller
    import cssutils
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait

    cssutils.log.setLevel(logging.CRITICAL)  # removes warning logs from cssutils
except ModuleNotFoundError as error:
    log.critical(f"ModuleNotFoundError: {error}. have your installed the requirements?")
    sys.exit(1)

from .conditions import notion_page_loaded, toggle_block_has_opened


class Parser:
    def __init__(self, config={}, args={}):
        self.config = config
        self.args = args
        index_url = self.config.get("page", None)
        if not index_url:
            log.critical(
                "No initial page url specified. If passing a configuration file,"
                " make sure it contains a 'page' key with the url of the notion.site"
                " page to parse"
            )
            raise Exception()

        # get the site name from the config, or make it up by cleaning the target page's slug
        site_name = self.config.get("name", self.get_page_slug(index_url, extension=False))

        self.index_url = index_url

        # set the output folder based on the site name
        self.dist_folder = Path(config.get("output", Path("dist") / site_name))
        log.info(f"Setting output path to '{self.dist_folder}'")

        # check if the argument to clean the dist folder was passed
        if self.args.get("clean", False):
            try:
                shutil.rmtree(self.dist_folder)
                log.info(f"Removing cached files in '{self.dist_folder}'")
            except OSError as e:
                log.error(f"Cannot remove '{self.dist_folder}': {e}")
        else:
            if self.args.get("clean_css", False):
                try:
                    log.info(f"Removing cached .css files in '{self.dist_folder}'")
                    for style_file in glob.glob(str(self.dist_folder / "*.css")):
                        os.remove(style_file)
                except OSError as e:
                    log.error(f"Cannot remove .css files in '{self.dist_folder}': {e}")
            if self.args.get("clean_js", False):
                try:
                    log.info(f"Removing cached .js files in '{self.dist_folder}'")
                    for style_file in glob.glob(str(self.dist_folder / "*.js")):
                        os.remove(style_file)
                except OSError as e:
                    log.error(f"Cannot remove .js files in '{self.dist_folder}': {e}")

        # create the output folder if necessary
        self.dist_folder.mkdir(parents=True, exist_ok=True)

        # initialize chromedriver
        self.driver = self.init_chromedriver()

        self.starting_url = index_url

    def get_page_config(self, token):
        # starts by grabbing the gobal site configuration table, if exists
        site_config = self.config.get("site", {})

        # check if there's anything wrong with the site config
        if site_config.get("slug", None):
            log.error(
                "'slug' parameter has no effect in the [site] table, "
                "and should only present in page tables."
            )
            del site_config["slug"]

        # find a table in the configuration file whose key contains the passed token string
        site_pages_config = self.config.get("pages", {})
        matching_pages_config = [
            value for key, value in site_pages_config.items() if key.lower() in token
        ]
        if matching_pages_config:
            if len(matching_pages_config) > 1:
                log.error(
                    f"multiple matching page config tokens found for {token}"
                    " in configuration file. Make sure pages urls / slugs are unique"
                )
                return site_config
            else:
                # if found, merge it on top of the global site configuration table
                # log.debug(f"Config table found for page with token {token}")
                matching_page_config = matching_pages_config[0]
                if type(matching_page_config) is dict:
                    return {**site_config, **matching_page_config}
                else:
                    log.error(
                        f"Matching page configuration for {token} was not a dict:"
                        f" {matching_page_config} - something went wrong"
                    )
                    return site_config
        else:
            # log.debug(f"No config table found for page token {token}, using global site config table")
            return site_config

    def get_page_slug(self, url, extension=True):
        # first check if the url has a custom slug configured in the config file
        custom_slug = self.get_page_config(url).get("slug", None)
        if custom_slug:
            log.debug(f"Custom slug found for url '{url}': '{custom_slug}'")
            return custom_slug.strip("/") + (".html" if extension else "")
        else:
            # if not, clean up the existing slug
            path = urllib.parse.urlparse(url).path.strip("/")
            if "-" in path and len(path.split("-")) > 1:
                # a standard notion page looks like the-page-title-[uiid]
                # strip the uuid and keep the page title only
                path = "-".join(path.split("-")[:-1]).lower()
            elif "?" in path:
                # database pages just have an uiid and a query param
                # not much to do here, just get rid of the query param
                path = path.split("?")[0].lower()
            return path + (".html" if extension else "")

    def cache_file(self, url, filename=None):
        # stringify the url in case it's a Path object
        url = str(url)

        # if no filename specificed, generate an hashed id based the query-less url,
        # so we avoid re-downloading / caching files we already have
        if not filename:
            parsed_url = urllib.parse.urlparse(url)
            queryless_url = parsed_url.netloc + parsed_url.path
            query_params = urllib.parse.parse_qs(parsed_url.query)
            # if any of the query params contains a size parameters store it in the has
            # so we can download other higher-resolution versions if needed
            if "width" in query_params.keys():
                queryless_url = queryless_url + f"?width={query_params['width']}"
            filename = hashlib.sha1(str.encode(queryless_url)).hexdigest()
        destination = self.dist_folder / filename

        # check if there are any files matching the filename, ignoring extension
        matching_file = glob.glob(str(destination.with_suffix(".*")))
        if not matching_file:
            # if url has a network scheme, download the file
            if "http" in urllib.parse.urlparse(url).scheme:
                try:
                    # Disabling proxy speeds up requests time
                    # https://stackoverflow.com/questions/45783655/first-https-request-takes-much-more-time-than-the-rest
                    # https://stackoverflow.com/questions/28521535/requests-how-to-disable-bypass-proxy
                    session = requests.Session()
                    session.trust_env = False
                    log.info(f"Downloading '{url}'")
                    response = session.get(url)

                    # if the filename does not have an extension at this point,
                    # try to infer it from the url, and if not possible,
                    # from the content-type header mimetype
                    if not destination.suffix:
                        file_extension = Path(urllib.parse.urlparse(url).path).suffix
                        if not file_extension:
                            content_type = response.headers.get("content-type")
                            if content_type:
                                file_extension = mimetypes.guess_extension(content_type)
                        elif "%3f" in file_extension.lower():
                            file_extension = re.split(
                                "%3f", file_extension, flags=re.IGNORECASE
                            )[0]
                        if file_extension:
                            destination = destination.with_suffix(file_extension)

                    Path(destination).parent.mkdir(parents=True, exist_ok=True)
                    with open(destination, "wb") as f:
                        f.write(response.content)

                    return destination.relative_to(self.dist_folder)
                except Exception as error:
                    log.error(f"Error downloading file '{url}': {error}")
                    return url
            # if not, check if it's a local file, and copy it to the dist folder
            else:
                if Path(url).is_file():
                    log.debug(f"Caching local file '{url}'")
                    destination = destination.with_suffix(Path(url).suffix)
                    shutil.copyfile(url, destination)
                    return destination.relative_to(self.dist_folder)
        # if we already have a matching cached file, just return its relative path
        else:
            cached_file = Path(matching_file[0]).relative_to(self.dist_folder)
            log.debug(f"'{url}' was already downloaded")
            return cached_file

    def init_chromedriver(self):
        chromedriver_path = self.args.get("chromedriver")
        if not chromedriver_path:
            try:
                chromedriver_path = chromedriver_autoinstaller.install()
            except Exception as exception:
                log.critical(
                    f"Failed to install the built-in chromedriver: {exception}\n"
                    "\nDownload the correct version for your system at"
                    " https://chromedriver.chromium.org/downloads and use the"
                    " --chromedriver argument to point to the chromedriver executable"
                )
                raise exception

        log.info(f"Initialising chromedriver at {chromedriver_path}")
        logs_path = Path.cwd() / ".logs" / "webdrive.log"
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        chrome_options = Options()
        if not self.args.get("non_headless", False):
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("window-size=1920,20000")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--silent")
        chrome_options.add_argument("--disable-logging")
        #  removes the 'DevTools listening' log message
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
        return webdriver.Chrome(
            executable_path=str(chromedriver_path),
            service_log_path=str(logs_path),
            options=chrome_options,
        )

    def parse_page(self, url: str):
        """Parse page at url and write it to file, then recursively parse all subpages.

        Args:
            url (str): URL of the page to parse.

        After the page at `url` has been parsed, calls itself recursively for every subpage
        it has discovered.
        """
        log.info(f"Parsing page '{url}'")
        log.debug(f"Using page config: {self.get_page_config(url)}")

        try:
            self.load_correct_theme(url)
        except TimeoutException as ex:
            log.critical(
                "Timeout waiting for page content to load, or no content found."
                " Are you sure the page is set to public?"
            )
            raise ex

        # open the toggle blocks in the page
        self.open_toggle_blocks(self.args["timeout"])

        # creates soup from the page to start parsing
        soup = BeautifulSoup(self.driver.page_source, "html5lib")

        self.clean_up(soup)
        self.set_custom_meta_tags(url, soup)
        self.process_images_and_emojis(soup)
        self.process_stylesheets(soup)
        self.add_toggle_custom_logic(soup)
        self.process_table_views(soup)
        self.embed_custom_fonts(url, soup)

        # inject any custom elements to the page
        custom_injects = self.get_page_config(url).get("inject", {})
        self.inject_custom_tags("head", soup, custom_injects)
        self.inject_custom_tags("body", soup, custom_injects)

        self.inject_loconotion_script_and_css(soup)

        hrefDomain = f'{url.split("notion.site")[0]}notion.site'
        log.info(f"Got the domain as {hrefDomain}")

        subpages = self.find_subpages(url, soup, hrefDomain)
        self.export_parsed_page(url, soup)
        self.parse_subpages(subpages)

    def load_correct_theme(self, url):
        self.load(url)

        # if dark theme is enabled, set local storage item and re-load the page
        if self.args.get("dark_theme", True):
            log.debug("Dark theme is enabled")
            self.driver.execute_script(
                "window.localStorage.setItem('theme','{\"mode\":\"dark\"}');"
            )
            self.load(url)

        # light theme is on by default
        # enable dark mode based on https://fruitionsite.com/ dark mode hack
        if self.config.get("theme") == "dark":
            self.driver.execute_script(
                "__console.environment.ThemeStore.setState({ mode: 'dark' });"
            )

    def open_toggle_blocks(self, timeout: int, exclude=[]):
        """Expand all the toggle block in the page to make their content visible

        Args:
            timeout (int): timeout in seconds
            exclude (list[Webelement], optional): toggles to exclude. Defaults to [].

        Opening toggles is needed for hooking up our custom toggle logic afterwards.
        """
        opened_toggles = exclude
        toggle_blocks = self.driver.find_elements_by_class_name("notion-toggle-block")
        toggle_blocks += self._get_title_toggle_blocks()
        log.debug(f"Opening {len(toggle_blocks)} new toggle blocks in the page")
        for toggle_block in toggle_blocks:
            if toggle_block not in opened_toggles:
                toggle_button = toggle_block.find_element_by_css_selector(
                    "div[role=button]"
                )
                # check if the toggle is already open by the direction of its arrow
                is_toggled = "(180deg)" in (
                    toggle_button.find_element_by_tag_name("svg").get_attribute("style")
                )
                if not is_toggled:
                    # click on it, then wait until all elements are displayed
                    self.driver.execute_script("arguments[0].click();", toggle_button)
                    try:
                        WebDriverWait(self.driver, timeout).until(
                            toggle_block_has_opened(toggle_block)
                        )
                    except TimeoutException as ex:
                        log.warning(
                            "Timeout waiting for toggle block to open."
                            " Likely it's already open, but doesn't hurt to check."
                        )
                    except Exception as exception:
                        log.error(f"Error trying to open a toggle block: {exception}")
                    opened_toggles.append(toggle_block)

        # after all toggles have been opened, check the page again to see if
        # any toggle block had nested toggle blocks inside them
        new_toggle_blocks = self.driver.find_elements_by_class_name(
            "notion-toggle-block"
        )
        new_toggle_blocks += self._get_title_toggle_blocks()
        if len(new_toggle_blocks) > len(toggle_blocks):
            # if so, run the function again
            self.open_toggle_blocks(timeout, opened_toggles)
        
    def _get_title_toggle_blocks(self):
        """Find toggle title blocks via their button element.
        """
        title_toggle_blocks = []
        header_types = ["header", "sub_header", "sub_sub_header"]
        for header_type in header_types:
            title_blocks = self.driver.find_elements_by_class_name(
                f"notion-selectable.notion-{header_type}-block"
            )
            for block in title_blocks:
                toggle_buttons = block.find_elements_by_css_selector("div[role=button]")
                if len(toggle_buttons) > 0:
                    title_toggle_blocks.append(block)
        return title_toggle_blocks
    
    def clean_up(self, soup):
        # remove scripts and other tags we don't want / need
        for unwanted in soup.findAll("script"):
            unwanted.decompose()
        for aif_production in soup.findAll("iframe", {"src": "https://aif.notion.so/aif-production.html"}):
            aif_production.decompose()
        for intercom_frame in soup.findAll("iframe", {"id": "intercom-frame"}):
            intercom_frame.decompose()
        for intercom_div in soup.findAll("div", {"class": "intercom-lightweight-app"}):
            intercom_div.decompose()
        for overlay_div in soup.findAll("div", {"class": "notion-overlay-container"}):
            overlay_div.decompose()
        for vendors_css in soup.find_all("link", href=lambda x: x and "vendors~" in x):
            vendors_css.decompose()

        # collection selectors (List, Gallery, etc.) don't work, so remove them
        for collection_selector in soup.findAll(
            "div", {"class": "notion-collection-view-select"}
        ):
            collection_selector.decompose()

        # clean up the default notion meta tags
        for tag in [
            "description",
            "twitter:card",
            "twitter:site",
            "twitter:title",
            "twitter:description",
            "twitter:image",
            "twitter:url",
            "apple-itunes-app",
        ]:
            unwanted_tag = soup.find("meta", attrs={"name": tag})
            if unwanted_tag:
                unwanted_tag.decompose()
        for tag in [
            "og:site_name",
            "og:type",
            "og:url",
            "og:title",
            "og:description",
            "og:image",
        ]:
            unwanted_og_tag = soup.find("meta", attrs={"property": tag})
            if unwanted_og_tag:
                unwanted_og_tag.decompose()

    def set_custom_meta_tags(self, url, soup):
        # set custom meta tags
        custom_meta_tags = self.get_page_config(url).get("meta", [])
        for custom_meta_tag in custom_meta_tags:
            tag = soup.new_tag("meta")
            for attr, value in custom_meta_tag.items():
                tag.attrs[attr] = value
            log.debug(f"Adding meta tag {str(tag)}")
            soup.head.append(tag)

    def process_images_and_emojis(self, soup):
        # process images & emojis
        cache_images = True
        for img in soup.findAll("img"):
            if img.has_attr("src"):
                if cache_images and "data:image" not in img["src"]:
                    img_src = img["src"]
                    # if the path starts with /, it's one of notion's predefined images
                    if img["src"].startswith("/"):
                        img_src = f'https://www.notion.so{img["src"]}'
                        # notion's own default images urls are in a weird format, need to sanitize them
                        # img_src = 'https://www.notion.so' + img['src'].split("notion.so")[-1].replace("notion.so", "").split("?")[0]
                        # if (not '.amazonaws' in img_src):
                        # img_src = urllib.parse.unquote(img_src)

                    cached_image = self.cache_file(img_src)
                    img["src"] = cached_image
                elif img["src"].startswith("/"):
                    img["src"] = f'https://www.notion.so{img["src"]}'

            # on emoji images, cache their sprite sheet and re-set their background url
            if img.has_attr("class") and "notion-emoji" in img["class"]:
                style = cssutils.parseStyle(img["style"])
                spritesheet = style["background"]
                spritesheet_url = spritesheet[
                    spritesheet.find("(") + 1 : spritesheet.find(")")
                ]
                cached_spritesheet_url = self.cache_file(
                    f"https://www.notion.so{spritesheet_url}"
                )

                style["background"] = spritesheet.replace(
                    spritesheet_url, str(cached_spritesheet_url)
                )
                img["style"] = style.cssText

    def process_stylesheets(self, soup):
        # process stylesheets
        for link in soup.findAll("link", rel="stylesheet"):
            if link.has_attr("href") and link["href"].startswith("/"):
                # we don't need the vendors stylesheet
                if "vendors~" in link["href"]:
                    continue
                cached_css_file = self.cache_file(
                    f'https://www.notion.so{link["href"]}'
                )
                # files in the css file might be reference with a relative path,
                # so store the path of the current css file
                parent_css_path = os.path.split(
                    urllib.parse.urlparse(link["href"]).path
                )[0]
                # open the locally saved file
                with open(self.dist_folder / cached_css_file, "rb+") as f:
                    stylesheet = cssutils.parseString(f.read())
                    # open the stylesheet and check for any font-face rule,
                    for rule in stylesheet.cssRules:
                        if rule.type == cssutils.css.CSSRule.FONT_FACE_RULE:
                            # if any are found, download the font file
                            # TODO: maths fonts have fallback font sources
                            font_file = (
                                rule.style["src"].split("url(")[-1].split(")")[0]
                            )
                            # assemble the url given the current css path
                            font_url = "/".join(
                                p.strip("/")
                                for p in [
                                    "https://www.notion.so",
                                    parent_css_path,
                                    font_file,
                                ]
                                if p.strip("/")
                            )
                            # don't hash the font files filenames, rather get filename only
                            cached_font_file = self.cache_file(
                                font_url, Path(font_file).name
                            )
                            rule.style["src"] = f"url({cached_font_file})"
                    # commit stylesheet edits to file
                    f.seek(0)
                    f.truncate()
                    f.write(stylesheet.cssText)

                link["href"] = str(cached_css_file)

    def add_toggle_custom_logic(self, soup):
        # add our custom logic to all toggle blocks
        toggle_blocks = soup.findAll("div", {"class": "notion-toggle-block"})
        toggle_blocks += self._get_title_toggle_blocks_soup(soup)
        for toggle_block in toggle_blocks:
            toggle_id = uuid.uuid4()
            toggle_button = toggle_block.select_one("div[role=button]")
            toggle_content = toggle_block.find("div", {"class": None, "style": ""})
            if toggle_button and toggle_content:
                # add a custom class to the toggle button and content,
                # plus a custom attribute sharing a unique uiid so
                # we can hook them up with some custom js logic later
                toggle_button["class"] = toggle_block.get("class", []) + [
                    "loconotion-toggle-button"
                ]
                toggle_content["class"] = toggle_content.get("class", []) + [
                    "loconotion-toggle-content"
                ]
                toggle_content.attrs["loconotion-toggle-id"] = toggle_button.attrs[
                    "loconotion-toggle-id"
                ] = toggle_id

    def _get_title_toggle_blocks_soup(self, soup):
        """Find title toggle blocks from soup.
        """
        title_toggle_blocks = []
        title_types = ["header", "sub_header", "sub_sub_header"]
        for title_type in title_types:
            title_blocks = soup.findAll(
                "div",
                {"class": f"notion-selectable notion-{title_type}-block"}
            )
            for block in title_blocks:
                if block.select_one("div[role=button]") is not None:
                    title_toggle_blocks.append(block)
        return title_toggle_blocks 

    def process_table_views(self, soup):
        # if there are any table views in the page, add links to the title rows
        # the link to the row item is equal to its data-block-id without dashes
        for table_view in soup.findAll("div", {"class": "notion-table-view"}):
            for table_row in table_view.findAll(
                "div", {"class": "notion-collection-item"}
            ):
                table_row_block_id = table_row["data-block-id"]
                table_row_href = "/" + table_row_block_id.replace("-", "")
                row_target_span = table_row.find("span")
                row_target_span["style"] = row_target_span["style"].replace(
                    "pointer-events: none;", ""
                )
                row_link_wrapper = soup.new_tag(
                    "a",
                    attrs={
                        "href": table_row_href,
                        "style": "cursor: pointer; color: inherit; text-decoration: none; fill: inherit;",
                    },
                )
                row_target_span.wrap(row_link_wrapper)

    def embed_custom_fonts(self, url, soup):
        if not (custom_fonts := self.get_page_config(url).get("fonts", {})):
            return

        # append a stylesheet importing the google font for each unique font
        unique_custom_fonts = set(custom_fonts.values())
        for font in unique_custom_fonts:
            if font:
                google_fonts_embed_name = font.replace(" ", "+")
                font_href = f"https://fonts.googleapis.com/css2?family={google_fonts_embed_name}:wght@500;600;700&display=swap"
                custom_font_stylesheet = soup.new_tag(
                    "link", rel="stylesheet", href=font_href
                )
                soup.head.append(custom_font_stylesheet)

        # go through each custom font, and add a css rule overriding the font-family
        # to the font override stylesheet targetting the appropriate selector
        font_override_stylesheet = soup.new_tag("style", type="text/css")
        # embed custom google font(s)
        fonts_selectors = {
            "site": "div:not(.notion-code-block)",
            "navbar": ".notion-topbar div",
            "title": ".notion-page-block > div, .notion-collection_view_page-block > div[data-root]",
            "h1": ".notion-header-block div, notion-page-content > notion-collection_view-block > div:first-child div",
            "h2": ".notion-sub_header-block div",
            "h3": ".notion-sub_sub_header-block div",
            "body": ".notion-scroller",
            "code": ".notion-code-block *",
        }
        for target, custom_font in custom_fonts.items():
            if custom_font and target != "site":
                log.debug(f"Setting {target} font-family to {custom_font}")
                font_override_stylesheet.append(
                    fonts_selectors[target]
                    + " {font-family:"
                    + custom_font
                    + " !important} "
                )

        site_font = custom_fonts.get("site", None)
        if site_font:
            log.debug(f"Setting global site font-family to {site_font}"),
            font_override_stylesheet.append(
                fonts_selectors["site"] + " {font-family:" + site_font + "} "
            )

        # finally append the font overrides stylesheets to the page
        soup.head.append(font_override_stylesheet)

    def inject_custom_tags(self, section: str, soup, custom_injects: dict):
        """Inject custom tags to the given section.

        Args:
            section (str): Section / tag name to insert into.
            soup (BeautifulSoup): a BeautifulSoup element holding the whole page.
            custom_injects (dict): description of custom tags to inject.
        """
        section_custom_injects = custom_injects.get(section, {})
        for tag, elements in section_custom_injects.items():
            for element in elements:
                injected_tag = soup.new_tag(tag)
                for attr, value in element.items():

                    # `inner_html` refers to the tag's inner content
                    # and will be added later
                    if attr == "inner_html":
                        continue

                    injected_tag[attr] = value
                    # if the value refers to a file, copy it to the dist folder
                    if attr.lower() in ["href", "src"]:
                        log.debug(f"Copying injected file '{value}'")
                        if urllib.parse.urlparse(value).scheme:
                            path_to_file = value
                        else:
                            path_to_file = Path.cwd() / value.strip("/")
                        cached_custom_file = self.cache_file(path_to_file)
                        injected_tag[attr] = str(cached_custom_file)  # source.name
                log.debug(f"Injecting <{section}> tag: {injected_tag}")

                # adding `inner_html` as the tag's content
                if "inner_html" in element:
                    injected_tag.string = element["inner_html"]

                soup.find(section).append(injected_tag)

    def inject_loconotion_script_and_css(self, soup):
        # inject loconotion's custom stylesheet and script
        loconotion_custom_css = self.cache_file(Path("bundles/loconotion.css"))
        custom_css = soup.new_tag(
            "link", rel="stylesheet", href=str(loconotion_custom_css)
        )
        soup.head.insert(-1, custom_css)
        loconotion_custom_js = self.cache_file(Path("bundles/loconotion.js"))
        custom_script = soup.new_tag(
            "script", type="text/javascript", src=str(loconotion_custom_js)
        )
        soup.body.insert(-1, custom_script)

    def find_subpages(self, url, soup, hrefDomain):
        # find sub-pages and clean slugs / links
        subpages = []
        parse_links = not self.get_page_config(url).get("no-links", False)
        for a in soup.find_all("a", href=True):
            sub_page_href = a["href"]
            if sub_page_href.startswith("/"):
                sub_page_href = (
                    f'{hrefDomain}/{a["href"].split("/")[len(a["href"].split("/"))-1]}'
                )
                log.info(f"Got this as href {sub_page_href}")
            if sub_page_href.startswith(hrefDomain):
                if parse_links or not len(
                    a.find_parents("div", class_="notion-scroller")
                ):
                    # if the link is an anchor link,
                    # check if the page hasn't already been parsed
                    if "#" in sub_page_href:
                        sub_page_href_tokens = sub_page_href.split("#")
                        sub_page_href = sub_page_href_tokens[0]
                        a["href"] = f"#{sub_page_href_tokens[-1]}"
                        a["class"] = a.get("class", []) + ["loconotion-anchor-link"]
                        if (
                            sub_page_href in self.processed_pages.keys()
                            or sub_page_href in subpages
                        ):
                            log.debug(
                                f"Original page for anchor link {sub_page_href}"
                                " already parsed / pending parsing, skipping"
                            )
                            continue
                    else:
                        extension_in_links = self.config.get("extension_in_links", True)
                        a["href"] = (
                            self.get_page_slug(sub_page_href, extension=extension_in_links)
                            if sub_page_href != self.index_url
                            else ("index.html" if extension_in_links else "")
                        )
                    subpages.append(sub_page_href)
                    log.debug(f"Found link to page {a['href']}")
                else:
                    # if the page is set not to follow any links, strip the href
                    # do this only on children of .notion-scroller, we don't want
                    # to strip the links from the top nav bar
                    log.debug(f"Stripping link for {a['href']}")
                    del a["href"]
                    a.name = "span"
                    # remove pointer cursor styling on the link and all children
                    for child in [a] + a.find_all():
                        if child.has_attr("style"):
                            style = cssutils.parseStyle(child["style"])
                            style["cursor"] = "default"
                            child["style"] = style.cssText
        return subpages

    def export_parsed_page(self, url, soup):
        # exports the parsed page
        html_str = str(soup)
        html_file = self.get_page_slug(url) if url != self.index_url else "index.html"
        if html_file in self.processed_pages.values():
            log.error(
                f"Found duplicate pages with slug '{html_file}' - previous one will be"
                " overwritten. Make sure that your notion pages names or custom slugs"
                " in the configuration files are unique"
            )
        log.info(f"Exporting page '{url}' as '{html_file}'")
        with open(self.dist_folder / html_file, "wb") as f:
            f.write(html_str.encode("utf-8").strip())
        self.processed_pages[url] = html_file

    def parse_subpages(self, subpages):
        # parse sub-pages
        if subpages and not self.args.get("single_page", False):
            if self.processed_pages:
                log.debug(f"Pages processed so far: {len(self.processed_pages)}")
            for sub_page in subpages:
                if sub_page not in self.processed_pages.keys():
                    self.parse_page(sub_page)

    def load(self, url):
        self.driver.get(url)
        WebDriverWait(self.driver, 60).until(notion_page_loaded())

    def run(self):
        start_time = time.time()
        self.processed_pages = {}
        self.parse_page(self.starting_url)
        elapsed_time = time.time() - start_time
        formatted_time = "{:02d}:{:02d}:{:02d}".format(
            int(elapsed_time // 3600),
            int(elapsed_time % 3600 // 60),
            int(elapsed_time % 60),
        )
        log.info(
            f"Finished!\n\nProcessed {len(self.processed_pages)} pages in {formatted_time}"
        )
