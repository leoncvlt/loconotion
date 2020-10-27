import os
import sys
import shutil
import time
import uuid
import logging
import re
import glob
import mimetypes
import urllib.parse
import hashlib
from pathlib import Path

log = logging.getLogger(f"loconotion.{__name__}")

try:
    import chromedriver_autoinstaller
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from bs4 import BeautifulSoup
    import requests
    import cssutils

    cssutils.log.setLevel(logging.CRITICAL)  # removes warning logs from cssutils
except ModuleNotFoundError as error:
    log.critical(f"ModuleNotFoundError: {error}. have your installed the requirements?")
    sys.exit()

from conditions import toggle_block_has_opened, notion_page_loaded


class Parser:
    def __init__(self, config={}, args={}):
        self.config = config
        self.args = args
        url = self.config.get("page", None)
        if not url:
            log.critical(
                "No initial page url specified. If passing a configuration file,"
                " make sure it contains a 'page' key with the url of the notion.so"
                " page to parse"
            )
            return

        # get the site name from the config, or make it up by cleaning the target page's slug
        site_name = self.config.get("name", self.get_page_slug(url, extension=False))

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

        # initialize chromedriver and start parsing
        self.driver = self.init_chromedriver()
        self.run(url)

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
                        f"Matching page configuration for {url} was not a dict:"
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
                        elif '%3f' in file_extension.lower():
                            file_extension = re.split("%3f", file_extension, flags=re.IGNORECASE)[0]
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
                sys.exit()

        log.info(f"Initialising chromedriver at {chromedriver_path}")
        logs_path = Path.cwd() / "logs" / "webdrive.log"
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        chrome_options = Options()
        if not self.args.get("non_headless", False):
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("window-size=1920,1080")
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
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

    def parse_page(self, url, processed_pages={}, index=None):
        # if this is the first page being parse, set it as the index.html
        if not index:
            index = url

        log.info(f"Parsing page '{url}'")
        log.debug(f"Using page config: {self.get_page_config(url)}")
        self.driver.get(url)

        try:
            WebDriverWait(self.driver, 60).until(notion_page_loaded())
        except TimeoutException as ex:
            log.critical(
                "Timeout waiting for page content to load, or no content found."
                " Are you sure the page is set to public?"
            )
            return

        # scroll at the bottom of the notion-scroller element to load all elements
        # continue once there are no changes in height after a timeout
        # don't do this if the page has a calendar databse on it or it will load forever
        calendar = self.driver.find_elements_by_class_name("notion-calendar-view")
        if not calendar:
            scroller = self.driver.find_element_by_css_selector(
                ".notion-frame > .notion-scroller"
            )
            last_height = scroller.get_attribute("scrollHeight")
            log.debug(f"Scrolling to bottom of notion-scroller (height: {last_height})")
            while True:
                self.driver.execute_script(
                    "arguments[0].scrollTo(0, arguments[0].scrollHeight)", scroller
                )
                time.sleep(self.args["timeout"])
                new_height = scroller.get_attribute("scrollHeight")
                log.debug(f"New notion-scroller height after timeout is: {new_height}")
                if new_height == last_height:
                    break
                last_height = new_height

        # function to expand all the toggle block in the page to make their content visible
        # so we can hook up our custom toggle logic afterwards
        def open_toggle_blocks(timeout, exclude=[]):
            opened_toggles = exclude
            toggle_blocks = self.driver.find_elements_by_class_name("notion-toggle-block")
            log.debug(f"Opening {len(toggle_blocks)} new toggle blocks in the page")
            for toggle_block in toggle_blocks:
                if not toggle_block in opened_toggles:
                    toggle_button = toggle_block.find_element_by_css_selector(
                        "div[role=button]"
                    )
                    # check if the toggle is already open by the direction of its arrow
                    is_toggled = "(180deg)" in (
                        toggle_button.find_element_by_tag_name("svg").get_attribute(
                            "style"
                        )
                    )
                    if not is_toggled:
                        # click on it, then wait until all elements are displayed
                        toggle_button.click()
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
            if len(new_toggle_blocks) > len(toggle_blocks):
                # if so, run the function again
                open_toggle_blocks(timeout, opened_toggles)

        # open the toggle blocks in the page
        open_toggle_blocks(self.args["timeout"])

        # creates soup from the page to start parsing
        soup = BeautifulSoup(self.driver.page_source, "html.parser")

        # remove scripts and other tags we don't want / need
        for unwanted in soup.findAll("script"):
            unwanted.decompose()
        for intercom_frame in soup.findAll("div", {"id": "intercom-frame"}):
            intercom_frame.decompose()
        for intercom_div in soup.findAll("div", {"class": "intercom-lightweight-app"}):
            intercom_div.decompose()
        for overlay_div in soup.findAll("div", {"class": "notion-overlay-container"}):
            overlay_div.decompose()
        for vendors_css in soup.find_all("link", href=lambda x: x and "vendors~" in x):
            vendors_css.decompose()

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

        # set custom meta tags
        custom_meta_tags = self.get_page_config(url).get("meta", [])
        for custom_meta_tag in custom_meta_tags:
            tag = soup.new_tag("meta")
            for attr, value in custom_meta_tag.items():
                tag.attrs[attr] = value
            log.debug(f"Adding meta tag {str(tag)}")
            soup.head.append(tag)

        # process images & emojis
        cache_images = True
        for img in soup.findAll("img"):
            if img.has_attr("src"):
                if cache_images and not "data:image" in img["src"]:
                    img_src = img["src"]
                    # if the path starts with /, it's one of notion's predefined images
                    if img["src"].startswith("/"):
                        img_src = "https://www.notion.so" + img["src"]
                        # notion's own default images urls are in a weird format, need to sanitize them
                        # img_src = 'https://www.notion.so' + img['src'].split("notion.so")[-1].replace("notion.so", "").split("?")[0]
                        # if (not '.amazonaws' in img_src):
                        # img_src = urllib.parse.unquote(img_src)

                    cached_image = self.cache_file(img_src)
                    img["src"] = cached_image
                else:
                    if img["src"].startswith("/"):
                        img["src"] = "https://www.notion.so" + img["src"]

            # on emoji images, cache their sprite sheet and re-set their background url
            if img.has_attr("class") and "notion-emoji" in img["class"]:
                style = cssutils.parseStyle(img["style"])
                spritesheet = style["background"]
                spritesheet_url = spritesheet[
                    spritesheet.find("(") + 1 : spritesheet.find(")")
                ]
                cached_spritesheet_url = self.cache_file(
                    "https://www.notion.so" + spritesheet_url
                )
                style["background"] = spritesheet.replace(
                    spritesheet_url, str(cached_spritesheet_url)
                )
                img["style"] = style.cssText

        # process stylesheets
        for link in soup.findAll("link", rel="stylesheet"):
            if link.has_attr("href") and link["href"].startswith("/"):
                # we don't need the vendors stylesheet
                if "vendors~" in link["href"]:
                    continue
                # css_file = link['href'].strip("/")
                cached_css_file = self.cache_file("https://www.notion.so" + link["href"])
                with open(self.dist_folder / cached_css_file, "rb") as f:
                    stylesheet = cssutils.parseString(f.read())
                    # open the stylesheet and check for any font-face rule,
                    for rule in stylesheet.cssRules:
                        if rule.type == cssutils.css.CSSRule.FONT_FACE_RULE:
                            # if any are found, download the font file
                            font_file = (
                                rule.style["src"].split("url(/")[-1].split(") format")[0]
                            )
                            cached_font_file = self.cache_file(
                                f"https://www.notion.so/{font_file}"
                            )
                            rule.style["src"] = f"url({str(cached_font_file)})"
                link["href"] = str(cached_css_file)

        # add our custom logic to all toggle blocks
        for toggle_block in soup.findAll("div", {"class": "notion-toggle-block"}):
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

        # if there are any table views in the page, add links to the title rows
        # the link to the row item is equal to its data-block-id without dashes
        for table_view in soup.findAll("div", {"class": "notion-table-view"}):
            for table_row in table_view.findAll(
                "div", {"class": "notion-collection-item"}
            ):
                table_row_block_id = table_row["data-block-id"]
                table_row_href = "/" + table_row_block_id.replace("-", "")
                row_target_span = table_row.find("span")
                row_link_wrapper = soup.new_tag(
                    "a", attrs={"href": table_row_href, "style": "cursor: pointer;"}
                )
                row_target_span.wrap(row_link_wrapper)

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
        custom_fonts = self.get_page_config(url).get("fonts", {})
        if custom_fonts:
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
            for target, custom_font in custom_fonts.items():
                if custom_font and not target == "site":
                    log.debug(f"Setting {target} font-family to {custom_font}")
                    font_override_stylesheet.append(
                        fonts_selectors[target]
                        + " {font-family:"
                        + custom_font
                        + " !important} "
                    )
            site_font = custom_fonts.get("site", None)
            # process global site font last to more granular settings can override it
            if site_font:
                log.debug(f"Setting global site font-family to {site_font}"),
                font_override_stylesheet.append(
                    fonts_selectors["site"] + " {font-family:" + site_font + "} "
                )
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
                        if attr.lower() == "href" or attr.lower() == "src":
                            log.debug(f"Copying injected file '{value}'")
                            cached_custom_file = self.cache_file(
                                (Path.cwd() / value.strip("/"))
                            )
                            # destination = (self.dist_folder / source.name)
                            # shutil.copyfile(source, destination)
                            injected_tag[attr] = str(cached_custom_file)  # source.name
                    log.debug(f"Injecting <{section}> tag: {str(injected_tag)}")
                    soup.find(section).append(injected_tag)

        injects_custom_tags("head")
        injects_custom_tags("body")

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

        # find sub-pages and clean slugs / links
        sub_pages = []
        for a in soup.findAll("a"):
            if a["href"].startswith("/"):
                sub_page_href = "https://www.notion.so" + a["href"]
                # if the link is an anchor link,
                # check if the page hasn't already been parsed
                if "#" in sub_page_href:
                    sub_page_href_tokens = sub_page_href.split("#")
                    sub_page_href = sub_page_href_tokens[0]
                    a["href"] = "#" + sub_page_href_tokens[-1]
                    a["class"] = a.get("class", []) + ["loconotion-anchor-link"]
                    if (
                        sub_page_href in processed_pages.keys()
                        or sub_page_href in sub_pages
                    ):
                        log.debug(
                            f"Original page for anchor link {sub_page_href}"
                            " already parsed / pending parsing, skipping"
                        )
                        continue
                else:
                    a["href"] = (
                        self.get_page_slug(sub_page_href)
                        if sub_page_href != index
                        else "index.html"
                    )
                sub_pages.append(sub_page_href)
                log.debug(f"Found link to page {a['href']}")

        # exports the parsed page
        html_str = str(soup)
        html_file = self.get_page_slug(url) if url != index else "index.html"
        if html_file in processed_pages.values():
            log.error(
                f"Found duplicate pages with slug '{html_file}' - previous one will be"
                " overwritten. Make sure that your notion pages names or custom slugs"
                " in the configuration files are unique"
            )
        log.info(f"Exporting page '{url}' as '{html_file}'")
        with open(self.dist_folder / html_file, "wb") as f:
            f.write(html_str.encode("utf-8").strip())
        processed_pages[url] = html_file

        # parse sub-pages
        if sub_pages and not self.args.get("single_page", False):
            if processed_pages:
                log.debug(f"Pages processed so far: {len(processed_pages)}")
            for sub_page in sub_pages:
                if not sub_page in processed_pages.keys():
                    self.parse_page(
                        sub_page, processed_pages=processed_pages, index=index
                    )

        # we're all done!
        return processed_pages

    def run(self, url):
        start_time = time.time()
        tot_processed_pages = self.parse_page(url)
        elapsed_time = time.time() - start_time
        formatted_time = "{:02d}:{:02d}:{:02d}".format(
            int(elapsed_time // 3600),
            int(elapsed_time % 3600 // 60),
            int(elapsed_time % 60),
            tot_processed_pages,
        )
        log.info(
            f"Finished!\n\nProcessed {len(tot_processed_pages)} pages in {formatted_time}"
        )
