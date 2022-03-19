from modules.notionparser import Parser

def test_parse_sample_page():
    config={"page": "https://www.notion.so/Loconotion-Example-Page-03c403f4fdc94cc1b315b9469a8950ef"}
    args = {"timeout": 10, "single_page": True}
    parser = Parser(config, args)
    parser.processed_pages = {}

    parser.parse_page(parser.starting_url)

    assert parser.starting_url in parser.processed_pages
