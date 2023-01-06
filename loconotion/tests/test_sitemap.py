import sys
sys.path.insert(0, "D:\\Other Projects\\loconotion\\loconotion")

from modules.notionparser import Parser

def test_parse_sample_page():
    config={"page": "https://www.notion.so/Loconotion-Example-Page-03c403f4fdc94cc1b315b9469a8950ef", "domain": "example.com"}
    args = {"timeout": 10, "single_page": True}
    parser = Parser(config, args)
    parser.run()
    pass

if __name__ == "__main__":
    test_parse_sample_page()
