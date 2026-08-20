from inferbench.main import discovery_urls


def test_discovery_accepts_models_or_chat_url():
    expected = (
        "https://example.com/v1/models",
        "https://example.com/v1/chat/completions",
    )
    assert discovery_urls("https://example.com/v1/models") == expected
    assert discovery_urls("https://example.com/v1/chat/completions") == expected


def test_discovery_accepts_server_root():
    assert discovery_urls("https://example.com") == (
        "https://example.com/v1/models",
        "https://example.com/v1/chat/completions",
    )
