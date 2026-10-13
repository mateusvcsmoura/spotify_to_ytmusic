#!/usr/bin/env python3
#
#  This file is licensed under the MIT license
#  This file originates from https://github.com/caseychu/spotify-backup

import base64
import codecs
import hashlib
import http.client
import http.server
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import certifi

# Windows only exposes root CAs it has already fetched; accounts.spotify.com chains to
# Starfield G2, which is often missing there.  certifi ships with requests/ytmusicapi.
_SSL = ssl.create_default_context(cafile=certifi.where())


class SpotifyAPI:
    """Class to interact with the Spotify API using an OAuth token."""

    BASE_URL = "https://api.spotify.com/v1/"

    def __init__(self, auth):
        self._auth = auth

    def get(self, url, params={}, tries=3):
        """Fetch a resource from Spotify API."""
        url = self._construct_url(url, params)
        for _ in range(tries):
            try:
                req = self._create_request(url)
                return self._read_response(req)
            except Exception as err:
                print(f"Error fetching URL {url}: {err}")
                time.sleep(2)
        sys.exit("Failed to fetch data from Spotify API after retries.")

    def list(self, url, params={}):
        """Fetch paginated resources and return as a combined list."""
        response = self.get(url, params)
        items = response["items"]

        while response["next"]:
            response = self.get(response["next"])
            items += response["items"]
        return items

    @staticmethod
    def authorize(client_id, scope):
        """Authorization Code + PKCE flow (Spotify removed the implicit grant in Nov 2025).

        Opens a browser for user authorization and returns a SpotifyAPI instance.
        """
        redirect_uri = f"http://127.0.0.1:{SpotifyAPI._SERVER_PORT}/redirect"
        verifier = secrets.token_urlsafe(64)
        url = SpotifyAPI._construct_auth_url(
            client_id, scope, redirect_uri, SpotifyAPI._pkce_challenge(verifier)
        )
        print(f"Open this link if the browser doesn't open automatically: {url}")
        webbrowser.open(url)

        server = SpotifyAPI._AuthorizationServer("127.0.0.1", SpotifyAPI._SERVER_PORT)
        try:
            while True:
                server.handle_request()
        except SpotifyAPI._Authorization as auth:
            code = auth.code
        finally:
            server.server_close()

        data = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            }
        ).encode()
        # ponytail: token lasts 1h with no refresh; a backup takes minutes.
        with urllib.request.urlopen(
            "https://accounts.spotify.com/api/token", data, context=_SSL
        ) as res:
            return SpotifyAPI(json.load(res)["access_token"])

    @staticmethod
    def _pkce_challenge(verifier):
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _construct_auth_url(client_id, scope, redirect_uri, code_challenge):
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "scope": scope,
                "redirect_uri": redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": code_challenge,
            }
        )

    def _construct_url(self, url, params):
        """Construct a full API URL."""
        if not url.startswith(self.BASE_URL):
            url = self.BASE_URL + url
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return url

    def _create_request(self, url):
        """Create an authenticated request."""
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._auth}")
        return req

    def _read_response(self, req):
        """Read and parse the response."""
        with urllib.request.urlopen(req, context=_SSL) as res:
            reader = codecs.getreader("utf-8")
            return json.load(reader(res))

    _SERVER_PORT = 43019

    class _AuthorizationServer(http.server.HTTPServer):
        def __init__(self, host, port):
            super().__init__((host, port), SpotifyAPI._AuthorizationHandler)

        def handle_error(self, request, client_address):
            raise

    class _AuthorizationHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if not self.path.startswith("/redirect"):
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<script>close()</script>Thanks! You may now close this window."
            )
            if "code" not in query:
                sys.exit(
                    f"Spotify authorization failed: {query.get('error', ['no code'])[0]}"
                )
            raise SpotifyAPI._Authorization(query["code"][0])

        def log_message(self, format, *args):
            pass

    class _Authorization(Exception):
        def __init__(self, code):
            self.code = code


def _tracks(items):
    """Normalize paging items to the {"track": {...}} shape backend.py reads.

    The Feb 2026 API renamed playlist entries "track" -> "item".  Podcast episodes
    and unavailable entries are dropped: they can't be matched on YTMusic.
    """
    tracks = [x.get("item") or x.get("track") for x in items]
    return [{"track": t} for t in tracks if t and t.get("type") == "track"]


def fetch_user_data(spotify, dump):
    """Fetch playlists and liked songs based on the dump parameter."""
    playlists = []
    liked_albums = []

    if "liked" in dump:
        print("Loading liked albums and songs...")
        liked_tracks = _tracks(spotify.list("me/tracks", {"limit": 50}))
        liked_albums = spotify.list("me/albums", {"limit": 50})
        playlists.append({"name": "Liked Songs", "tracks": liked_tracks})

    if "playlists" in dump:
        print("Loading playlists...")
        my_id = spotify.get("me")["id"]
        for playlist in spotify.list("me/playlists", {"limit": 50}):
            # Since Feb 2026 Spotify only returns the contents of playlists you own
            # or collaborate on; followed playlists come back without tracks.
            if playlist["owner"]["id"] != my_id and not playlist.get("collaborative"):
                print(f"Skipping (followed, not yours): {playlist['name']}")
                continue
            print(f"Loading playlist: {playlist['name']}")
            playlist["tracks"] = _tracks(
                spotify.list(f"playlists/{playlist['id']}/items", {"limit": 50})
            )
            playlists.append(playlist)

    return playlists, liked_albums


def write_to_file(file, format, playlists, liked_albums):
    """Write fetched data to a file in the specified format."""
    print(f"Writing to {file}...")
    with open(file, "w", encoding="utf-8") as f:
        if format == "json":
            json.dump({"playlists": playlists, "albums": liked_albums}, f)
        else:
            for playlist in playlists:
                f.write(playlist["name"] + "\r\n")
                for track in playlist["tracks"]:
                    if track["track"]:
                        f.write(
                            "{name}\t{artists}\t{album}\t{uri}\t{release_date}\r\n".format(
                                uri=track["track"]["uri"],
                                name=track["track"]["name"],
                                artists=", ".join(
                                    [
                                        artist["name"]
                                        for artist in track["track"]["artists"]
                                    ]
                                ),
                                album=track["track"]["album"]["name"],
                                release_date=track["track"]["album"]["release_date"],
                            )
                        )
                f.write("\r\n")


def main(dump="playlists,liked", format="json", file="playlists.json", token=""):
    print("Starting backup...")
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not token and not client_id:
        sys.exit(
            "ERROR: SPOTIFY_CLIENT_ID is not set.  Fill it in the .env file (see the comments there)."
        )
    spotify = (
        SpotifyAPI(token)
        if token
        else SpotifyAPI.authorize(
            client_id=client_id,
            scope="playlist-read-private playlist-read-collaborative user-library-read",
        )
    )

    playlists, liked_albums = fetch_user_data(spotify, dump)
    write_to_file(file, format, playlists, liked_albums)
    print(f"Backup completed! Data written to {file}")


if __name__ == "__main__":
    main()
