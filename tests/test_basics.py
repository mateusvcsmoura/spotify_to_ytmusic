#!/usr/bin/env python

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import spotify2ytmusic
from spotify2ytmusic import spotify_backup


class TestSpotifyBackup(unittest.TestCase):
    def test_tracks_normalizes_item_and_track(self):
        new, old = {"type": "track", "name": "New"}, {"type": "track", "name": "Old"}
        items = [
            {"item": new},
            {"track": old},
            {"item": {"type": "episode", "name": "Podcast"}},
            {"item": None},
        ]
        self.assertEqual(
            spotify_backup._tracks(items), [{"track": new}, {"track": old}]
        )

    def test_pkce_challenge_rfc7636_vector(self):
        self.assertEqual(
            spotify_backup.SpotifyAPI._pkce_challenge(
                "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
            ),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )

    def test_load_dotenv_keeps_cookie_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# comment\nS2YT_A=a=1; b=2\nS2YT_B=\"quoted\"\nS2YT_C=\n")
            with patch.dict(os.environ, {}, clear=True):
                spotify2ytmusic.load_dotenv(path)
                self.assertEqual(os.environ["S2YT_A"], "a=1; b=2")
                self.assertEqual(os.environ["S2YT_B"], "quoted")
                self.assertNotIn("S2YT_C", os.environ)


class TestCopier(unittest.TestCase):
    @patch("spotify2ytmusic.cli.YTMusic")
    def test_copier_success(self, mock_ytmusic):
        # Setup mock responses
        mock_ytmusic_instance = MagicMock()
        mock_ytmusic.return_value = mock_ytmusic_instance
        mock_ytmusic_instance.get_playlist.return_value = {"title": "Test Playlist"}
        mock_ytmusic_instance.add_playlist_items.return_value = None

        spotify2ytmusic.cli.copier(
            spotify2ytmusic.cli.iter_spotify_playlist(
                "68QlHDwCiXfhodLpS72iOx",
                spotify_playlist_file="tests/playliststest.json",
            ),
            dst_pl_id="dst_test",
        )

        mock_ytmusic_instance.get_playlist.assert_called_once_with(
            playlistId="dst_test"
        )

    @patch("spotify2ytmusic.cli.YTMusic")
    def test_copier_albums(self, mock_ytmusic):
        # Setup mock responses
        mock_ytmusic_instance = MagicMock()
        mock_ytmusic.return_value = mock_ytmusic_instance
        mock_ytmusic_instance.get_playlist.return_value = {"title": "Test Playlist"}
        mock_ytmusic_instance.add_playlist_items.return_value = None

        spotify2ytmusic.cli.copier(
            spotify2ytmusic.cli.iter_spotify_liked_albums(
                spotify_playlist_file="tests/playliststest.json"
            ),
            dst_pl_id="dst_test",
        )

        mock_ytmusic_instance.get_playlist.assert_called_once_with(
            playlistId="dst_test"
        )

    @patch("spotify2ytmusic.cli.YTMusic")
    def test_copier_liked_playlists(self, mock_ytmusic):
        # Setup mock responses
        mock_ytmusic_instance = MagicMock()
        mock_ytmusic.return_value = mock_ytmusic_instance
        mock_ytmusic_instance.get_playlist.return_value = {"title": "Test Playlist"}
        mock_ytmusic_instance.add_playlist_items.return_value = None

        spotify2ytmusic.cli.copier(
            spotify2ytmusic.cli.iter_spotify_playlist(
                None, spotify_playlist_file="tests/playliststest.json"
            ),
            dst_pl_id="dst_test",
            track_sleep=0,
        )

        mock_ytmusic_instance.get_playlist.assert_called_once_with(
            playlistId="dst_test"
        )


if __name__ == "__main__":
    unittest.main()
