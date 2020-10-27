import os
import sys
import logging
import urllib.parse
import argparse
from pathlib import Path

log = logging.getLogger("loconotion")

try:
    import requests
    import toml
except ModuleNotFoundError as error:
    log.critical(f"ModuleNotFoundError: {error}. have your installed the requirements?")
    sys.exit()

from notionparser import Parser


def main():
    # set up argument parser
    argparser = argparse.ArgumentParser(
        description="Generate static websites from Notion.so pages"
    )
    argparser.add_argument(
        "target",
        help="The config file containing the site properties, or the url"
        " of the Notion.so page to generate the site from",
    )
    argparser.add_argument(
        "--chromedriver",
        help="Use a specific chromedriver executable instead of the auto-installing one",
    )
    argparser.add_argument(
        "--single-page", action="store_true", help="Only parse the first page, then stop"
    )
    argparser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Time in seconds to wait for the loading of lazy-loaded dynamic elements (default 5)."
        " If content from the page seems to be missing, try increasing this value",
    )
    argparser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all previously cached files for the site before generating it",
    )
    argparser.add_argument(
        "--clean-css",
        action="store_true",
        help="Delete previously cached .css files for the site before generating it",
    )
    argparser.add_argument(
        "--clean-js",
        action="store_true",
        help="Delete previously cached .js files for the site before generating it",
    )
    argparser.add_argument(
        "--non-headless",
        action="store_true",
        help="Run chromedriver in non-headless mode",
    )
    argparser.add_argument(
        "-v", "--verbose", action="store_true", help="Increase output log verbosity"
    )
    args = argparser.parse_args()

    # set up some pretty logs
    log = logging.getLogger("loconotion")
    log.setLevel(logging.INFO if not args.verbose else logging.DEBUG)
    log_screen_handler = logging.StreamHandler(stream=sys.stdout)
    log.addHandler(log_screen_handler)
    log.propagate = False
    try:
        import colorama, copy

        LOG_COLORS = {
            logging.DEBUG: colorama.Fore.GREEN,
            logging.INFO: colorama.Fore.BLUE,
            logging.WARNING: colorama.Fore.YELLOW,
            logging.ERROR: colorama.Fore.RED,
            logging.CRITICAL: colorama.Back.RED,
        }

        class ColorFormatter(logging.Formatter):
            def format(self, record, *args, **kwargs):
                # if the corresponding logger has children, they may receive modified
                # record, so we want to keep it intact
                new_record = copy.copy(record)
                if new_record.levelno in LOG_COLORS:
                    new_record.levelname = "{color_begin}{level}{color_end}".format(
                        level=new_record.levelname,
                        color_begin=LOG_COLORS[new_record.levelno],
                        color_end=colorama.Style.RESET_ALL,
                    )
                return super(ColorFormatter, self).format(new_record, *args, **kwargs)

        log_screen_handler.setFormatter(
            ColorFormatter(
                fmt="%(asctime)s %(levelname)-8s %(message)s",
                datefmt="{color_begin}[%H:%M:%S]{color_end}".format(
                    color_begin=colorama.Style.DIM, color_end=colorama.Style.RESET_ALL
                ),
            )
        )
    except ModuleNotFoundError as identifier:
        pass

    # initialise and run the website parser
    try:
        if urllib.parse.urlparse(args.target).scheme:
            try:
                response = requests.get(args.target)
                if "notion.so" in args.target:
                    log.info("Initialising parser with simple page url")
                    config = {"page": args.target}
                    Parser(config=config, args=vars(args))
                else:
                    log.critical(f"{args.target} is not a notion.so page")
            except requests.ConnectionError as exception:
                log.critical(f"Connection error")
        else:
            if Path(args.target).is_file():
                with open(args.target) as f:
                    parsed_config = toml.loads(f.read())
                    log.info(f"Initialising parser with configuration file")
                    log.debug(parsed_config)
                    Parser(config=parsed_config, args=vars(args))
            else:
                log.critical(f"Config file {args.target} does not exists")
    except FileNotFoundError as e:
        log.critical(f"FileNotFoundError: {e}")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.critical("Interrupted by user")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
