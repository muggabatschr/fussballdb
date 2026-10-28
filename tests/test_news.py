from fussballdb.ingest.news import kind, parse

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Alarmstimmung beim VfB: Anlass zur Sorge - Zeitungsverlag Waiblingen</title><link>https://news.google.com/a</link>
<pubDate>Tue, 27 Oct 2026 14:35:00 GMT</pubDate><source url="https://www.zvw.de">Zeitungsverlag Waiblingen</source></item>
<item><title>VfB Stuttgart: Hoeneß vor dem Pokalspiel - Kicker</title><link>https://news.google.com/b</link>
<pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate><source url="https://www.kicker.de">Kicker</source></item>
<item><title>‍!$>[LIVE!#Ansehen]* VfB Stuttgart heute übertragung - Spam</title><link>https://news.google.com/c</link>
<pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate><source url="https://spam.org">Spam</source></item>
<item><title>VfB-Frauen gewinnen deutlich - SWR</title><link>https://news.google.com/d</link>
<pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate><source url="https://www.swr.de">SWR</source></item>
<item><title>Training am Wasen - VfB Stuttgart</title><link>https://news.google.com/e</link>
<pubDate>Tue, 27 Oct 2026 09:00:00 GMT</pubDate><source url="https://www.vfb.de">VfB Stuttgart</source></item>
</channel></rss>"""


def test_parse_strips_source_filters_spam_and_marks_local():
    items = parse(FEED, "VfB Stuttgart")
    assert [(i["title"], i["kind"]) for i in items] == [
        ("Alarmstimmung beim VfB: Anlass zur Sorge", "lokal"),
        ("VfB Stuttgart: Hoeneß vor dem Pokalspiel", None),
        ("Training am Wasen", "verein"),
    ]


def test_kind_by_domain():
    assert kind("Hamburger SV", "https://www.abendblatt.de") == "lokal"
    assert kind("SV Werder Bremen", "https://www.abendblatt.de") is None
    assert kind("Borussia Dortmund", "https://www.bvb.de") == "verein"


def test_clean_title_removes_sections_and_paywall_marks():
    from fussballdb.ingest.news import clean_title

    assert clean_title("Fußball-Bundesliga - FC Bayern siegt in Freiburg - Bayern - SZ.de - SZ.de", "SZ.de") == "FC Bayern siegt in Freiburg"
    assert clean_title("(S+) Spätes Tor sichert BVB-Heimsieg - Spiegel", "Spiegel") == "Spätes Tor sichert BVB-Heimsieg"
    assert clean_title("Philippe trifft - HSV verliert in Paderborn - NDR.de", "NDR.de") == "Philippe trifft - HSV verliert in Paderborn"


def test_press_line_prefers_match_headlines_and_skips_noise():
    from datetime import datetime, timezone

    from fussballdb.reports import _press_line

    t = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)
    n = lambda title, kind="lokal": {"title": title, "source": "BZ", "kind": kind, "published_at": t}  # noqa: E731
    m = {"home": "SC Freiburg", "away": "FC Bayern München", "home_short": "Freiburg", "away_short": "Bayern",
         "press_home": [n("Die Bilder zum Heimspiel gegen Bayern"), n("SC Freiburg - FC Bayern"),
                        n("Der SC schnuppert gegen die Bayern am Ausgleich"), n("Kurz gespielt KW44", "verein")],
         "press_away": [n("Transfergerücht um Musiala", None)]}
    assert _press_line(m) == "Pressestimmen: „Der SC schnuppert gegen die Bayern am Ausgleich“ (BZ)."


def test_about_team_needs_club_or_player_not_city():
    from fussballdb.ingest.news import NICK, about_team

    words = set(NICK["VfB Stuttgart"]) | {"assignon"}
    assert about_team("Alarmstimmung beim VfB", words)
    assert about_team("Der Fehlstart des Lorenz Assignon", words)
    assert not about_team("S-Bahnen in der Region Stuttgart: Baum umgestürzt", words)
