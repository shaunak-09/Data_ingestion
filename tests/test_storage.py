"""Object storage version checks."""

from unittest.mock import Mock

from azure.core import MatchConditions

from src.storage import BlobObjectStore


def test_blob_download_is_conditioned_on_the_listed_etag():
    store = BlobObjectStore.__new__(BlobObjectStore)
    store._client = Mock()
    downloader = Mock()
    downloader.read.return_value = b""
    store._client.get_blob_client.return_value.download_blob.return_value = downloader

    with store.open_stream(
        "landing",
        "students.csv",
        expected_version='"listed-etag"',
    ):
        pass

    store._client.get_blob_client.return_value.download_blob.assert_called_once_with(
        etag='"listed-etag"',
        match_condition=MatchConditions.IfNotModified,
    )


def test_blob_move_is_conditioned_on_the_listed_etag():
    store = BlobObjectStore.__new__(BlobObjectStore)
    store._client = Mock()

    source = Mock()
    downloader = Mock()
    downloader.read.return_value = b""
    source.download_blob.return_value = downloader
    destination = Mock()
    store._client.get_blob_client.side_effect = [source, destination]

    store.move(
        "landing",
        "students.csv",
        "processed",
        expected_version='"listed-etag"',
    )

    options = {
        "etag": '"listed-etag"',
        "match_condition": MatchConditions.IfNotModified,
    }
    source.download_blob.assert_called_once_with(**options)
    source.delete_blob.assert_called_once_with(**options)
