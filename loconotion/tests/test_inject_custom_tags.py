import pytest
from unittest.mock import call, MagicMock
from modules.notionparser import Parser
import urllib

@pytest.fixture
def parser():
    config={"page": "https://some.page"}
    return Parser(config, {})

@pytest.fixture
def soup():
    tag = MagicMock()
    soup = MagicMock()
    soup.new_tag.return_value = tag
    return soup

def test_inject_file(parser: Parser, soup):
    custom_injects = {
        "body": {
            "script": [
                {
                    "src": "loconotion/tests/test_file.txt"
                }
            ]
        }
    }
    parser.inject_custom_tags("body", soup, custom_injects)
    assert soup.new_tag.return_value.__setitem__.call_args == call("src", "c93ac3dbe4fa24abcb232ef9c63a633661226a3f.txt")

def test_inject_url(parser: Parser, soup):
    custom_injects = {
        "body": {
            "script": [
                {
                    "src": "https://www.googletagmanager.com/gtag/js"
                }
            ]
        }
    }
    parser.inject_custom_tags("body", soup, custom_injects)
    assert soup.new_tag.return_value.__setitem__.call_args == call("src", "dc00f9243e99763056cd06fc0e8d431de42022e7")
