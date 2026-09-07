from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, WOAS, ID3NoHeaderError

from app.models import DownloadedMedia, MediaCandidate, TrackInfo

logger = logging.getLogger(__name__)

ALLOWED_INPUT_HOSTS = {
    "rj.app",
    "www.rj.app",
    "radiojavan.com",
    "www.radiojavan.com",
    "play.radiojavan.com",
}
MEDIA_HOSTS = (
    "host2.rj-mw1.com",
    "host1.rj-mw1.com",
    "host2.rjapp-content.app",
    "host1.rjapp-content.app",
)
MEDIA_HOST_SUFFIXES = (".rj-mw1.com", ".rjapp-content.app")
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
RJ_ORIGIN = "https://play.radiojavan.com"
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
RJ_PAGE_LINK_RE = re.compile(
    r"https://play\.radiojavan\.com/(song|podcast|video|music_video)/([^\s\"'<>?#]+)",
    re.IGNORECASE,
)
RJ_RELATIVE_PAGE_LINK_RE = re.compile(
    r"/(song|podcast|video|music_video)/([^\s\"'<>?#/]+)",
    re.IGNORECASE,
)


class RadioJavanError(Exception):
    """Base error shown as a safe user-facing message."""


class UnsupportedLinkError(RadioJavanError):
    pass


class MediaNotFoundError(RadioJavanError):
    pass


class MediaTooLargeError(RadioJavanError):
    def __init__(self, candidate: MediaCandidate, limit_bytes: int) -> None:
        self.candidate = candidate
        self.limit_bytes = limit_bytes
        super().__init__("The media is larger than the configured Telegram upload limit.")


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,);]}")


def normalize_input_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url.lstrip('/')}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_INPUT_HOSTS:
        raise UnsupportedLinkError("Please send a Radio Javan or rj.app link.")
    if parsed.scheme not in {"http", "https"}:
        raise UnsupportedLinkError("Only HTTP/HTTPS Radio Javan links are supported.")
    return url


def public_page_url(url: str) -> str:
    """Return the public Radio Javan player URL without contacting rj.app.

    rj.app is a short/deep-link host and may reject non-browser HTTP clients with
    403 even though its public destination is play.radiojavan.com.  The short
    path itself contains the media token, so known rj.app paths can be mapped to
    the public player host locally.  Tracking query parameters such as ``sid``
    are intentionally discarded.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"rj.app", "www.rj.app"}:
        return url

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise UnsupportedLinkError(
            "This rj.app link does not contain a supported Radio Javan media path."
        )

    return f"{RJ_ORIGIN}/{parts[0]}/{parts[1]}"


def _safe_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in MEDIA_HOSTS or any(host.endswith(suffix) for suffix in MEDIA_HOST_SUFFIXES)


def _first_string(obj: dict, keys: Iterable[str]) -> str | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _artist_name(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        return _first_string(value, ("name", "artist", "title"))
    if isinstance(value, list):
        names = [name for item in value if (name := _artist_name(item))]
        return ", ".join(names) or None
    return None


def _duration_seconds(value: object) -> int | None:
    if isinstance(value, (int, float)) and value > 0:
        seconds = float(value)
        if seconds > 100_000:
            seconds /= 1000
        return int(seconds)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return _duration_seconds(int(stripped))
        parts = stripped.split(":")
        if 1 < len(parts) <= 3 and all(part.isdigit() for part in parts):
            total = 0
            for part in parts:
                total = total * 60 + int(part)
            return total
    return None


def _find_api_track(payload: object) -> dict | None:
    if isinstance(payload, dict):
        has_identity = (
            isinstance(payload.get("permlink"), str)
            or isinstance(payload.get("title"), str)
        )
        has_media = any(isinstance(payload.get(key), str) for key in ("link", "hq_link", "lq_link"))
        if has_identity and has_media:
            return payload
        for value in payload.values():
            found = _find_api_track(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_api_track(item)
            if found:
                return found
    return None


def _candidate_key(candidate: MediaCandidate) -> tuple[str, str]:
    return candidate.url, candidate.quality


class RadioJavanClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 25,
        api_key: str | None = None,
        rj_user_agent: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.rj_user_agent = rj_user_agent
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": BROWSER_UA, "Accept": "*/*"},
        )

    async def __aenter__(self) -> RadioJavanClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.client.aclose()

    async def resolve(self, input_url: str) -> TrackInfo:
        input_url = normalize_input_url(input_url)
        resolved_url, html = await self._resolve_and_read_page(input_url)
        media_type, media_id, canonical_url = self._identify_media(resolved_url, html)

        page_title, page_cover = self._page_metadata(html)
        title = page_title or media_id
        track = TrackInfo(
            input_url=input_url,
            resolved_url=resolved_url,
            media_id=media_id,
            media_type=media_type,
            title=title,
            cover_url=page_cover,
            page_url=canonical_url or resolved_url,
        )

        api_item = await self._fetch_api_metadata(media_type, media_id, track.page_url)
        api_urls: list[str] = []
        if api_item:
            permlink = _first_string(api_item, ("permlink",))
            if permlink:
                track.media_id = permlink
            track.title = _first_string(api_item, ("title", "song", "name")) or track.title
            track.artist = _artist_name(api_item.get("artist") or api_item.get("artists"))
            track.album = _first_string(api_item, ("album", "album_name"))
            track.duration = _duration_seconds(api_item.get("duration") or api_item.get("time"))
            track.cover_url = _first_string(
                api_item,
                ("photo_player", "photo", "image", "cover", "thumbnail"),
            ) or track.cover_url
            for key in ("hq_link", "link", "lq_link"):
                value = api_item.get(key)
                if isinstance(value, str) and _safe_media_url(value):
                    api_urls.append(value)

        track.candidates = self._build_candidates(track.media_type, track.media_id, api_urls)
        candidate = await self._find_working_candidate(track.candidates)
        if not candidate:
            raise MediaNotFoundError(
                "No public downloadable media file was found for this Radio Javan link."
            )
        track.candidates = [candidate] + [c for c in track.candidates if c.url != candidate.url]
        return track

    async def download(
        self,
        track: TrackInfo,
        output_dir: Path,
        *,
        max_bytes: int,
    ) -> DownloadedMedia:
        candidate = track.candidates[0]
        if candidate.content_length and candidate.content_length > max_bytes:
            raise MediaTooLargeError(candidate, max_bytes)

        safe_name = re.sub(r"[^\w\-. ]+", "_", track.title, flags=re.UNICODE).strip(" ._")
        if not safe_name:
            safe_name = track.media_id
        path = output_dir / f"{safe_name[:100]}.{candidate.extension}"

        logger.info(
            "Downloading Radio Javan media | quality=%s | url=%s",
            candidate.quality,
            candidate.url,
        )
        total = 0
        try:
            async with self.client.stream(
                "GET",
                candidate.url,
                headers={"Referer": track.page_url or RJ_ORIGIN},
            ) as response:
                response.raise_for_status()
                with path.open("wb") as file:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise MediaTooLargeError(candidate, max_bytes)
                        file.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise

        if candidate.extension == "mp3":
            await self._write_id3(path, track)
        return DownloadedMedia(path=path, track=track, candidate=candidate)

    async def _resolve_and_read_page(self, url: str) -> tuple[str, str]:
        request_url = public_page_url(url)
        if request_url != url:
            logger.info(
                "Mapped rj.app short link to public player URL | %s -> %s",
                url,
                request_url,
            )
        try:
            async with self.client.stream("GET", request_url) as response:
                response.raise_for_status()
                final_url = str(response.url)
                final_host = (response.url.host or "").lower()
                if final_host not in ALLOWED_INPUT_HOSTS:
                    raise UnsupportedLinkError(
                        "The Radio Javan short link redirected to an unexpected host."
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    content.extend(chunk)
                    if len(content) >= 2 * 1024 * 1024:
                        break
            return final_url, bytes(content).decode("utf-8", errors="ignore")
        except httpx.HTTPError as exc:
            logger.warning(
                "Unable to read Radio Javan public page %s (input %s): %s",
                request_url,
                url,
                exc,
            )
            raise RadioJavanError(
                "Radio Javan's public player page could not be reached. "
                "Please try again later."
            ) from exc

    def _identify_media(self, resolved_url: str, html: str) -> tuple[str, str, str | None]:
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.find("link", rel="canonical")
        canonical_url = canonical.get("href") if canonical and canonical.get("href") else None

        candidates = [canonical_url, resolved_url]
        og_url = soup.find("meta", attrs={"property": "og:url"})
        if og_url and og_url.get("content"):
            candidates.insert(0, og_url.get("content"))

        match = RJ_PAGE_LINK_RE.search(html)
        if match:
            candidates.insert(0, match.group(0))
        else:
            relative_match = RJ_RELATIVE_PAGE_LINK_RE.search(html)
            if relative_match:
                candidates.insert(
                    0,
                    f"{RJ_ORIGIN}/{relative_match.group(1)}/{relative_match.group(2)}",
                )

        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            parsed = urlparse(candidate)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 2:
                continue
            raw_type, media_id = parts[0].lower(), parts[1]
            if raw_type == "song":
                return "song", media_id, candidate
            if raw_type == "podcast":
                return "podcast", media_id, candidate
            if raw_type in {"video", "music_video"}:
                return "video", media_id, candidate
            if raw_type == "m":
                return "auto", media_id, candidate

        raise UnsupportedLinkError(
            "This Radio Javan URL type is not supported. "
            "Send a song, podcast, video, or rj.app media link."
        )

    @staticmethod
    def _page_metadata(html: str) -> tuple[str | None, str | None]:
        soup = BeautifulSoup(html, "html.parser")
        title_meta = soup.find("meta", attrs={"property": "og:title"})
        image_meta = soup.find("meta", attrs={"property": "og:image"})
        title = title_meta.get("content") if title_meta and title_meta.get("content") else None
        cover = image_meta.get("content") if image_meta and image_meta.get("content") else None
        if title:
            title = re.sub(r"\s*[|\-–]\s*Radio Javan.*$", "", title, flags=re.IGNORECASE).strip()
        return title or None, cover or None

    async def _fetch_api_metadata(
        self,
        media_type: str,
        media_id: str,
        page_url: str | None,
    ) -> dict | None:
        if media_type not in {"song", "auto"} or not self.api_key:
            return None
        headers = {
            "User-Agent": BROWSER_UA,
            "Accept": "application/json, text/plain, */*",
            "Origin": RJ_ORIGIN,
            "Referer": page_url or f"{RJ_ORIGIN}/song/{media_id}",
            "x-api-key": self.api_key,
        }
        if self.rj_user_agent:
            headers["x-rj-user-agent"] = self.rj_user_agent
        try:
            response = await self.client.get(
                f"{RJ_ORIGIN}/api/p/mp3",
                params={"id": media_id},
                headers=headers,
            )
            response.raise_for_status()
            return _find_api_track(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Optional Radio Javan metadata API failed: %s", exc)
            return None

    def _build_candidates(
        self,
        media_type: str,
        media_id: str,
        api_urls: list[str],
    ) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []

        def push(url: str, quality: str, kind: str, extension: str) -> None:
            if not _safe_media_url(url):
                return
            item = MediaCandidate(url=url, quality=quality, media_type=kind, extension=extension)
            if _candidate_key(item) not in {_candidate_key(existing) for existing in candidates}:
                candidates.append(item)

        for url in api_urls:
            if "mp3-320" in url.lower():
                quality = "320 kbps"
            elif "mp3-256" in url.lower():
                quality = "256 kbps"
            else:
                quality = "Source"
            extension = "mp4" if urlparse(url).path.lower().endswith(".mp4") else "mp3"
            push(url, quality, "video" if extension == "mp4" else "song", extension)

        types = ("song", "podcast", "video") if media_type == "auto" else (media_type,)
        identifiers = (media_id, media_id.lower()) if media_id.lower() != media_id else (media_id,)
        for kind in types:
            for host in MEDIA_HOSTS:
                for identifier in identifiers:
                    if kind == "song":
                        push(
                            f"https://{host}/media/mp3/mp3-320/{identifier}.mp3",
                            "320 kbps",
                            kind,
                            "mp3",
                        )
                        push(
                            f"https://{host}/media/mp3/mp3-256/{identifier}.mp3",
                            "256 kbps",
                            kind,
                            "mp3",
                        )
                    elif kind == "podcast":
                        push(
                            f"https://{host}/media/podcast/mp3-320/{identifier}.mp3",
                            "320 kbps",
                            kind,
                            "mp3",
                        )
                        push(
                            f"https://{host}/media/podcast/mp3-256/{identifier}.mp3",
                            "256 kbps",
                            kind,
                            "mp3",
                        )
                    elif kind == "video":
                        push(
                            f"https://{host}/media/music_video/hd/{identifier}.mp4",
                            "HD",
                            kind,
                            "mp4",
                        )
                        push(
                            f"https://{host}/media/music_video/sd/{identifier}.mp4",
                            "SD",
                            kind,
                            "mp4",
                        )
        return candidates

    async def _find_working_candidate(
        self, candidates: list[MediaCandidate]
    ) -> MediaCandidate | None:
        for candidate in candidates:
            try:
                response = await self.client.head(
                    candidate.url,
                    headers={"Referer": RJ_ORIGIN},
                )
                if response.is_success:
                    length = response.headers.get("content-length")
                    candidate.content_length = int(length) if length and length.isdigit() else None
                    if candidate.content_length is None or candidate.content_length >= 100:
                        return candidate
            except httpx.HTTPError:
                pass

            try:
                async with self.client.stream(
                    "GET",
                    candidate.url,
                    headers={"Range": "bytes=0-1", "Referer": RJ_ORIGIN},
                ) as response:
                    if response.status_code not in {200, 206}:
                        continue
                    length = response.headers.get("content-range") or response.headers.get(
                        "content-length"
                    )
                    if length and "/" in length:
                        tail = length.rsplit("/", 1)[-1]
                        candidate.content_length = int(tail) if tail.isdigit() else None
                    elif length and length.isdigit() and response.status_code == 200:
                        candidate.content_length = int(length)
                    async for _ in response.aiter_bytes(2):
                        break
                    return candidate
            except httpx.HTTPError:
                continue
        return None

    async def _write_id3(self, path: Path, track: TrackInfo) -> None:
        try:
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("TIT2")
            tags.add(TIT2(encoding=3, text=track.title))
            if track.artist:
                tags.delall("TPE1")
                tags.add(TPE1(encoding=3, text=track.artist))
            if track.album:
                tags.delall("TALB")
                tags.add(TALB(encoding=3, text=track.album))
            if track.page_url:
                tags.delall("WOAS")
                tags.add(WOAS(url=track.page_url))
            cover = await self._download_cover(track.cover_url)
            if cover:
                mime, data = cover
                tags.delall("APIC")
                tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            tags.save(path, v2_version=3)
        except Exception as exc:  # metadata failure must not lose the media
            logger.warning("Could not write MP3 metadata for %s: %s", path.name, exc)

    async def _download_cover(self, url: str | None) -> tuple[str, bytes] | None:
        if not url or not url.lower().startswith("https://"):
            return None
        try:
            response = await self.client.get(url, headers={"Referer": RJ_ORIGIN})
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if not content_type.startswith("image/") or len(response.content) > 3 * 1024 * 1024:
                return None
            return content_type, response.content
        except httpx.HTTPError:
            return None
