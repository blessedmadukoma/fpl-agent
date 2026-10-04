from fpl.config import Settings
from fpl.fplapi import FplClient


def test_client_tracks_written_raw_responses(tmp_path):
    client = FplClient(Settings(entry_id=None, data_dir=tmp_path))

    target = client._write_raw("bootstrap-static/", {"events": []})

    assert client.saved_raw_paths == (target,)
    assert target.is_file()
