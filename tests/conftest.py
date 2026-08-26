"""Test configuration

Provided fixtures:
- workspace:        Point the workspace at a temporary directory so test files land inside it
- tree:             Build the standard glob test tree (used by glob_tool tests)
- grep_tree:        Build the standard grep test tree (used by grep_tool tests)
- fake_ddgs:        Replace _web.DDGS with a configurable fake (web_search tests stay offline)
- fake_tavily:      Replace _web.TavilyClient with a configurable fake (search/extract paths stay offline)
- fake_crawler:     Replace _web._get_crawler with a fake crawler (web_fetch main path stays offline)
"""

import pytest

from core.tools._kernel import _web
from utils.settings import settings


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path))
    return tmp_path


@pytest.fixture()
def tree(workspace):
    files = {
        "hello.py": "print('hello')\n",
        "main.py": "print('main')\n",
        "x.py": "print('x')\n",
        "README.md": "# readme\n",
        "data.txt": "data\n",
        ".hidden.txt": "secret\n",
        ".DS_Store": "ds\n",
        ".venv/venv.py": "print('venv')\n",
        "logs/app.log": "log\n",
        "a/b.py": "print('b')\n",
        "a/c/note.txt": "note\n",
        "b/note.txt": "note\n",
        "sub/data.txt": "data\n",
        "sub/nested/deep.py": "print('deep')\n",
    }
    for rel, content in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


@pytest.fixture()
def grep_tree(workspace):
    files = {
        "a.py": "foo bar\nhello foo\nnothing here\nFOO case\nfoo\n",
        "b.py": "bar foo\nfoo foo foo\n",
        "sub/c.py": "hello\nfoo baz\n",
        "sub/d.txt": "no match here\n",
        "deep/nested/e.py": "foo deep\n",
        ".hidden.txt": "foo hidden\n",
        ".DS_Store": "foo\n",
        ".venv/f.py": "foo\n",
    }
    for rel, content in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


@pytest.fixture
def fake_ddgs(monkeypatch):

    class FakeDDGS:
        results = []
        error = None
        last_call = None

        def __init__(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def text(self, query, max_results=20):
            type(self).last_call = (query, max_results)
            if type(self).error is not None:
                raise type(self).error
            return type(self).results

    monkeypatch.setattr(_web, "DDGS", FakeDDGS)
    return FakeDDGS


@pytest.fixture
def fake_tavily(monkeypatch):

    class FakeTavilyClient:
        results = []
        extract_results = []
        error = None
        last_kwargs = None

        def __init__(self, api_key=None):
            self.api_key = api_key

        def search(self, **kwargs):
            type(self).last_kwargs = kwargs
            if type(self).error is not None:
                raise type(self).error
            return {"results": type(self).results}

        def extract(self, urls=None):
            type(self).last_kwargs = {"urls": urls}
            if type(self).error is not None:
                raise type(self).error
            return {"results": type(self).extract_results}

    monkeypatch.setattr(_web, "TavilyClient", FakeTavilyClient)
    return FakeTavilyClient


@pytest.fixture
def fake_crawler(monkeypatch):

    class FakeMarkdown:
        def __init__(self, fit, raw):
            self.fit_markdown = fit
            self.raw_markdown = raw

    class FakeResult:
        def __init__(self, fit, raw):
            self.markdown = FakeMarkdown(fit, raw)

    class FakeCrawler:
        markdown = (None, None)
        error = None
        arun_called = False

        @classmethod
        async def arun(cls, url=None, config=None):
            cls.arun_called = True
            if cls.error is not None:
                raise cls.error
            fit, raw = cls.markdown
            return FakeResult(fit, raw)

    async def _fake_get_crawler():
        return FakeCrawler

    monkeypatch.setattr(_web, "_get_crawler", _fake_get_crawler)
    return FakeCrawler
