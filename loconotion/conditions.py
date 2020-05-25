import logging

log = logging.getLogger(f"loconotion.{__name__}")


class notion_page_loaded(object):
    """An expectation for checking that a notion page has loaded."""

    def __call__(self, driver):
        notion_presence = len(
            driver.find_elements_by_class_name("notion-presence-container")
        )
        if (notion_presence):
            unknown_blocks = len(driver.find_elements_by_class_name("notion-unknown-block"))
            loading_spinners = len(driver.find_elements_by_class_name("loading-spinner"))
            scrollers = driver.find_elements_by_class_name("notion-scroller")
            scrollers_with_children = [];
            for scroller in scrollers:
                children = len(scroller.find_elements_by_tag_name("div"))
                if children > 0:
                    scrollers_with_children.append(scroller)
            log.debug(
                f"Waiting for page content to load"
                f" (pending blocks: {unknown_blocks},"
                f" loading spinners: {loading_spinners},"
                f" loaded scrollers: {len(scrollers_with_children)} / {len(scrollers)})"
            )
            all_scrollers_loaded = len(scrollers) == len(scrollers_with_children)
            if (all_scrollers_loaded and not unknown_blocks and not loading_spinners):
                return True
            else:
                return False
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
            unknown_children = len(
                toggle_content.find_elements_by_class_name("notion-unknown-block")
            )
            is_loading = len(
                self.toggle_block.find_elements_by_class_name("loading-spinner")
            )
            log.debug(
                f"Waiting for toggle block to load"
                f" (pending blocks: {unknown_children}, loaders: {is_loading})"
            )
            if not unknown_children and not is_loading:
                return True
            else:
                return False
        else:
            return False
