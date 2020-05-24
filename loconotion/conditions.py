import logging

log = logging.getLogger(f"loconotion.{__name__}")


class notion_page_loaded(object):
    """An expectation for checking that a notion page has loaded."""

    def __init__(self, url):
        self.url = url

    def __call__(self, driver):
        notion_presence = len(
            driver.find_elements_by_class_name("notion-presence-container")
        )
        collection_view_block = len(
            driver.find_elements_by_class_name("notion-collection_view_page-block")
        )
        collection_search = len(driver.find_elements_by_class_name("collectionSearch"))
        # embed_ghosts = len(driver.find_elements_by_css_selector("div[embed-ghost]"));
        log.debug(
            f"Waiting for page content to load"
            f" (presence container: {notion_presence}, loaders: {loading_spinners} )"
        )
        if notion_presence and not loading_spinners:
            return True
        else:
            return False


class toggle_block_has_opened(object):
    """An expectation for checking that a notion toggle block has been opened.
  It does so by checking if the div hosting the content has enough children,
  and the abscence of the loading spinner."""

    def __init__(self, toggle_block):
        self.toggle_block = toggle_block

    def __call__(self, driver):
        toggle_content = self.toggle_block.find_element_by_css_selector("div:not([style]")
        if toggle_content:
            content_children = len(toggle_content.find_elements_by_tag_name("div"))
            unknown_children = len(toggle_content.find_elements_by_class_name("notion-unknown-block"))
            is_loading = len(
                self.toggle_block.find_elements_by_class_name("loading-spinner")
            )
            log.debug(
                f"Waiting for toggle block to load"
                f" ({unknown_children} pending children blocks / {is_loading} loaders)"
            )
            if not unknown_children and not is_loading:
                return True
            else:
                return False
        else:
            return False
