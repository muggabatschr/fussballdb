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
