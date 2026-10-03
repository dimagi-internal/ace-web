"""Retargeting a cloned Google Doc at the clone's own copies (dimagi-internal/ace#2607).

Pure tests over ``documents.get``-shaped JSON. The live fault: a cloned run's
onboarding-email Doc linked the SOURCE run's FAQ, deck and quick reference, and
the FLW guide hid 23 source screenshot links behind link text.
"""
from apps.opps.doc_ids import id_pattern, retarget_requests, text_and_links

SRC_FAQ = "1FaqSourceAAAAAAAAAAAAAAAAAAAAAAA"
SRC_DECK = "1DeckSourceBBBBBBBBBBBBBBBBBBBBBB"
COPY_FAQ = "1FaqCopyCCCCCCCCCCCCCCCCCCCCCCCCC"
COPY_DECK = "1DeckCopyDDDDDDDDDDDDDDDDDDDDDDDD"
IDS = {SRC_FAQ: COPY_FAQ, SRC_DECK: COPY_DECK}


def _run(text, start, url=None):
    style = {"link": {"url": url}} if url else {}
    return {
        "startIndex": start, "endIndex": start + len(text),
        "textRun": {"content": text, "textStyle": style},
    }


def _para(*elements):
    return {"paragraph": {"elements": list(elements)}}


def _doc(*content, **segments):
    return {"body": {"content": list(content)}, **segments}


def test_id_pattern_matches_whole_ids_longest_first():
    pat = id_pattern(["abc", "abc-1"])
    assert [m.group(1) for m in pat.finditer("abc abc-1 xabc abc_2")] == ["abc", "abc-1"]
    assert id_pattern([]) is None


def test_link_retarget_comes_before_text_replace():
    doc = _doc(_para(
        _run("Read the FAQ", 1, f"https://docs.google.com/document/d/{SRC_FAQ}/edit"),
        _run(f" (id {SRC_DECK})\n", 13),
    ))
    requests, n = retarget_requests(doc, IDS)
    assert requests == [
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 13},
            "textStyle": {"link": {"url": f"https://docs.google.com/document/d/{COPY_FAQ}/edit"}},
            "fields": "link",
        }},
        {"replaceAllText": {
            "containsText": {"text": SRC_DECK, "matchCase": True},
            "replaceText": COPY_DECK,
        }},
    ]
    assert n == 2


def test_link_hidden_behind_link_text_is_found():
    # The FLW guide's screenshot links: no id in the visible text at all.
    doc = _doc(_para(_run("screenshot", 1, f"https://drive.google.com/file/d/{SRC_DECK}/view")))
    text, links = text_and_links(doc)
    assert SRC_DECK not in text
    requests, n = retarget_requests(doc, IDS)
    assert [list(r) for r in requests] == [["updateTextStyle"]]
    assert n == 1


def test_tables_headers_and_footnotes_are_walked():
    cell = {"content": [_para(_run("deck\n", 5, f"https://x/{SRC_DECK}"))]}
    doc = _doc(
        {"table": {"tableRows": [{"tableCells": [cell]}]}},
        {"tableOfContents": {"content": [_para(_run(f"{SRC_FAQ}\n", 20))]}},
        headers={"kix.h1": {"content": [_para(_run("faq", 0, f"https://x/{SRC_FAQ}"))]}},
    )
    requests, n = retarget_requests(doc, IDS)
    ranges = [r["updateTextStyle"]["range"] for r in requests if "updateTextStyle" in r]
    assert ranges == [
        {"startIndex": 5, "endIndex": 10},
        {"startIndex": 0, "endIndex": 3, "segmentId": "kix.h1"},
    ]
    assert {"replaceAllText": {"containsText": {"text": SRC_FAQ, "matchCase": True},
                               "replaceText": COPY_FAQ}} in requests
    assert n == 3


def test_a_doc_already_pointing_at_copies_needs_nothing():
    doc = _doc(_para(
        _run("FAQ", 1, f"https://docs.google.com/document/d/{COPY_FAQ}/edit"),
        _run(f" {COPY_DECK}\n", 4),
    ))
    assert retarget_requests(doc, IDS) == ([], 0)


def test_id_also_inside_a_longer_token_is_not_replaced_as_text():
    # replaceAllText is a substring replace: it would corrupt the longer token.
    doc = _doc(_para(_run(f"{SRC_FAQ} and {SRC_FAQ}x\n", 1)))
    assert retarget_requests(doc, IDS) == ([], 0)


def test_no_ids_no_requests():
    doc = _doc(_para(_run("x", 1, f"https://x/{SRC_FAQ}")))
    assert retarget_requests(doc, {}) == ([], 0)


# --- the real client wires get -> requests -> batchUpdate --------------------

class _Call:
    def __init__(self, result=None):
        self.result = result

    def execute(self):
        return self.result


class _Documents:
    def __init__(self, doc):
        self.doc = doc
        self.batches = []

    def get(self, documentId):
        return _Call(self.doc)

    def batchUpdate(self, documentId, body):
        self.batches.append((documentId, body))
        return _Call({})


class _Docs:
    def __init__(self, doc):
        self.docs = _Documents(doc)

    def documents(self):
        return self.docs


def _google_client(doc):
    from apps.opps.drive_client import GoogleDriveClient

    client = GoogleDriveClient.__new__(GoogleDriveClient)
    client._docs_service = _Docs(doc)
    return client


def test_google_client_batch_updates_only_when_something_changes():
    doc = _doc(_para(_run("FAQ", 1, f"https://x/{SRC_FAQ}")))
    client = _google_client(doc)
    assert client.retarget_doc_ids("doc-1", IDS) == 1
    [(doc_id, body)] = client._docs_service.docs.batches
    assert doc_id == "doc-1"
    assert body == {"requests": retarget_requests(doc, IDS)[0]}

    clean = _google_client(_doc(_para(_run("FAQ", 1, f"https://x/{COPY_FAQ}"))))
    assert clean.retarget_doc_ids("doc-2", IDS) == 0
    assert clean._docs_service.docs.batches == []


def test_cached_client_delegates_retarget():
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

    fake = FakeDriveClient.from_tree({"F": {}})
    doc_id = fake.upload_file(fake.folder_id("F"), "Doc", f"id {SRC_FAQ}\n",
                              "application/vnd.google-apps.document")
    fake.set_doc_links(doc_id, [f"https://x/{SRC_DECK}"])
    cached = CachedDriveClient(fake)
    assert cached.retarget_doc_ids(doc_id, IDS) == 2
    assert fake.doc_links(doc_id) == [f"https://x/{COPY_DECK}"]
