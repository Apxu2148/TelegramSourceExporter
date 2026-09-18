from datetime import date

import requests

from src.telegram_public_web import PublicWebFetcher


class FakeResponse:
    def __init__(self, text="", status_code=200, content=b"", headers=None):
        self.text = text
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        if url.startswith("https://cdn.example/photo.jpg"):
            return FakeResponse(content=b"jpg", headers={"content-type": "image/jpeg"})
        return FakeResponse(
            text="""
            <div class="tgme_channel_info_header_title">Banksta</div>
            <div class="tgme_widget_message" data-post="banksta/123">
              <time datetime="2026-05-01T06:15:00+00:00"></time>
              <div class="tgme_widget_message_text">Hello</div>
              <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example/photo.jpg')"></a>
            </div>
            """
        )


def test_public_web_without_proxy_keeps_session_defaults():
    fetcher = PublicWebFetcher()

    assert fetcher.session.proxies == {}
    assert fetcher.session.trust_env is True


def test_public_web_applies_socks5_proxy_to_requests(monkeypatch):
    captured: dict[str, object] = {}

    def fake_send(self, request, **kwargs):
        captured["proxies"] = kwargs.get("proxies")
        response = requests.Response()
        response.status_code = 200
        response._content = b"<html></html>"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    proxy = {"http": "socks5h://127.0.0.1:11808", "https": "socks5h://127.0.0.1:11808"}

    fetcher = PublicWebFetcher(proxy=proxy)
    assert fetcher.session.proxies["https"] == "socks5h://127.0.0.1:11808"
    assert fetcher.session.trust_env is False

    fetcher.session.get("https://t.me/s/banksta", timeout=30)

    assert captured["proxies"] == proxy


def test_public_web_parses_messages_and_downloads_image(tmp_path):
    session = FakeSession()
    source, messages = PublicWebFetcher(session).fetch_messages_for_day("@banksta", date(2026, 5, 1), True, tmp_path, "banksta")

    assert source.title == "Banksta"
    assert len(messages) == 1
    assert messages[0].message_id == "123"
    assert messages[0].media == "image"
    assert messages[0].media_files
    assert (tmp_path / messages[0].media_files[0]).exists()


class PaginatedSession:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        if "before=200" in url:
            return FakeResponse(
                text="""
                <div class="tgme_channel_info_header_title">Banksta</div>
                <div class="tgme_widget_message" data-post="banksta/150">
                  <time datetime="2026-05-01T08:00:00+00:00"></time>
                  <div class="tgme_widget_message_text">Target day</div>
                </div>
                <div class="tgme_widget_message" data-post="banksta/140">
                  <time datetime="2026-04-30T18:00:00+00:00"></time>
                  <div class="tgme_widget_message_text">Older day</div>
                </div>
                """
            )
        return FakeResponse(
            text="""
            <div class="tgme_channel_info_header_title">Banksta</div>
            <div class="tgme_widget_message" data-post="banksta/200">
              <time datetime="2026-05-02T08:00:00+00:00"></time>
              <div class="tgme_widget_message_text">Newer day</div>
            </div>
            """
        )


def test_public_web_paginates_until_target_day(tmp_path):
    session = PaginatedSession()
    _, messages = PublicWebFetcher(session, max_pages=5).fetch_messages_for_day(
        "@banksta",
        date(2026, 5, 1),
        False,
        tmp_path,
        "banksta",
    )

    assert [message.text for message in messages] == ["Target day"]
    assert session.urls == ["https://t.me/s/banksta", "https://t.me/s/banksta?before=200"]
