"""Water Babies API for Home Assistant."""
import json
import re
from datetime import datetime
import logging

from bs4 import BeautifulSoup
import requests

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://my.waterbabies.co.uk"
MONTHS_TO_FETCH = 3


class WaterBabiesAPI:
    """API for Water Babies."""

    def __init__(self, hass: HomeAssistant, username, password, session=None) -> None:
        """Initialize the API."""
        self._hass = hass
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._csrf_token = None

        # Make requests look browser-ish
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            )
        })

    async def async_get_csrf_token(self):
        """Load login page and extract csrf_swimphony."""
        url = f"{BASE_URL}/member/member/login/"
        _LOGGER.debug("Loading login page to get CSRF token")

        response = await self._hass.async_add_executor_job(self._session.get, url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        csrf_input = soup.find(
            "input",
            {"name": "csrf_swimphony"}
        )

        if not csrf_input:
            raise RuntimeError(
                "Could not find csrf_swimphony"
            )

        self._csrf_token = csrf_input.get("value")
        _LOGGER.debug("CSRF token found: %s", self._csrf_token)
        return self._csrf_token

    async def async_login(self):
        """Authenticate."""
        if not self._csrf_token:
            await self.async_get_csrf_token()

        url = f"{BASE_URL}/member/member/login/"
        _LOGGER.debug("Attempting to log in")

        payload = {
            "member_username": self._username,
            "member_password": self._password,
            "csrf_swimphony": self._csrf_token,
        }

        response = await self._hass.async_add_executor_job(
            lambda: self._session.post(
                url,
                data=payload,
                headers={
                    "Referer": url,
                    "Origin": BASE_URL,
                },
                allow_redirects=True,
            )
        )
        response.raise_for_status()

        # crude login validation
        if "member_username" in response.text:
            _LOGGER.debug("Login failed - Response: %s", response)
            raise RuntimeError(
                "Login appears to have failed. Check credentials."
            )

        _LOGGER.info("Logged in successfully")

    async def async_get_baby_ids(self):
        """Load member courses page and extract baby IDs."""
        url = f"{BASE_URL}/member/courses"
        _LOGGER.debug("Loading courses page to get baby IDs")


        response = await self._hass.async_add_executor_job(
            lambda: self._session.post(
                url,
                data={
                    "csrf_swimphony": self._csrf_token
                },
                headers={
                    "Referer": url,
                    "Origin": BASE_URL,
                },
                allow_redirects=True,
            )
        )
        
        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        select = soup.find(
            "select",
            {"id": "carer_baby"}
        )

        if not select:
            raise RuntimeError(
                "Could not find baby selector"
            )

        baby_ids = []

        for option in select.find_all("option"):
            value = option.get("value", "").strip()

            if value:
                baby_ids.append(value)

        _LOGGER.debug("Found baby IDs: %s", baby_ids)
        return baby_ids

    async def async_get_all_lessons(self):
        """Get all lessons for all babies."""
        await self.async_login()
        baby_ids = await self.async_get_baby_ids()

        all_lessons = []
        for baby_id in baby_ids:
            lessons = await self.async_get_baby_details(baby_id)
            all_lessons.extend(lessons)
        return all_lessons

    async def async_get_baby_details(self, baby_id):
        """Get lessons across multiple months."""
        url = (
            f"{BASE_URL}"
            "/member/courses/babyDetailsAjax"
        )

        _LOGGER.debug(
            "Getting lesson details for baby_id=%s",
            baby_id
        )

        response = await self._hass.async_add_executor_job(
                lambda: self._session.post(
                    url,
                    data={
                        "baby_id": baby_id,
                        "csrf_swimphony": self._csrf_token,
                },
                headers={
                    "X-Requested-With":
                        "XMLHttpRequest",
                    "Referer":
                        f"{BASE_URL}/member/courses",
                    "Origin":
                        BASE_URL,
                    "Accept":
                        "application/json, text/plain, */*",
                },
            )
        )

        _LOGGER.debug(
            "babyDetailsAjax status: %s",
            response.status_code
        )

        response.raise_for_status()

        data = response.json()
        
        # Update CSRF token if a new one is provided in JSON
        if "csrf_token" in data:
            self._csrf_token = data["csrf_token"]

        soup = BeautifulSoup(
            data["html"],
            "html.parser"
        )

        # ---- Handle inactive child ----

        lesson_span = soup.select_one(
            ".text-label span"
        )

        if not lesson_span:
            _LOGGER.debug(
                "Skipping %s (no lesson info found)",
                baby_id
            )
            return []

        schedule_text = (
            lesson_span.get_text(
                " ",
                strip=True,
            )
        )

        if (
            schedule_text.lower()
            == "no active lessons"
        ):
            _LOGGER.debug(
                "Skipping %s (no active lessons)",
                baby_id
            )
            return []

        # ---- Child name ----

        child_name = "Unknown"

        profile = soup.select_one(
            ".profile-dis p"
        )

        if profile:
            text = profile.get_text(
                " ",
                strip=True,
            )

            match = re.match(
                r"(.+?) will normally",
                text,
            )

            if match:
                child_name = (
                    match.group(1)
                )

        # ---- Time parsing ----

        start_time, end_time = (
            self._parse_schedule_time(
                schedule_text
            )
        )

        # ---- Venue ----

        venue_lines = soup.select(
            ".address li"
        )

        venue_parts = []
        for line in venue_lines:
            text = line.get_text(strip=True).strip(",")
            if text:
                venue_parts.append(text)

        venue = ", ".join(venue_parts)

        metadata = {
            "child_name": child_name,
            "start_time": start_time,
            "end_time": end_time,
            "venue": venue,
        }

        all_lessons = []
        all_lessons.extend(
            self._parse_calendar_rows(
                soup,
                metadata,
            )
        )

        next_button = soup.select_one('a.get_data[data-type="next"]')

        for _ in range(MONTHS_TO_FETCH - 1):
            if not next_button:
                break

            payload = {
                "start_date": next_button.get("data-start_date"),
                "get_month": next_button.get("data-get_month"),
                "type": "next",
                "timetable": next_button.get("data-timetable"),
                "baby": next_button.get("data-baby"),
                "class": next_button.get("data-class")
            }

            cal_url = (
                f"{BASE_URL}"
                "/member/courses/babyCalendarDetailsAjax"
            )

            _LOGGER.debug("Fetching next month: %s", payload)

            response = await self._hass.async_add_executor_job(
                lambda: self._session.post(
                    cal_url,
                    data=payload,
                    headers={
                        "X-Csrf-Token": self._csrf_token,
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": f"{BASE_URL}/member/courses",
                        "Origin": BASE_URL,
                    },
                )
            )
            response.raise_for_status()

            data = response.json()
            
            # Update CSRF token if a new one is provided
            if "csrf_token" in data:
                self._csrf_token = data["csrf_token"]

            soup = BeautifulSoup(
                data["html"],
                "html.parser",
            )

            all_lessons.extend(
                self._parse_calendar_rows(
                    soup,
                    metadata,
                )
            )

            next_button = soup.select_one('a.get_data[data-type="next"]')

        _LOGGER.debug(
            "Found %s lessons for %s",
            len(all_lessons),
            child_name
        )

        return all_lessons

    def _parse_schedule_time(self, schedule_text):
        """
        Example:
        Sunday 2:00 PM - 2:30 PM
        """

        match = re.search(
            r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
            schedule_text,
            re.IGNORECASE,
        )

        if not match:
            raise RuntimeError(
                f"Could not parse lesson time: {schedule_text}"
            )

        start = match.group(1)
        end = match.group(2)

        return start, end

    def _parse_calendar_rows(self, soup, metadata):
        """Parse lesson rows."""

        lessons = []

        month_heading = soup.find(
            "span",
            style=lambda s:
            s and
            "min-width" in s,
        )

        if not month_heading:
            return lessons

        heading_text = (
            month_heading.get_text(
                strip=True
            )
        )

        month_date = datetime.strptime(
            heading_text,
            "%B %Y",
        )

        year = month_date.year

        rows = soup.select(
            ".lesson-list table tr"
        )

        for row in rows:
            td = row.find("td")

            if not td:
                continue

            text = td.get_text(
                " ",
                strip=True,
            )

            date_match = re.search(
                r"(\d{2}/\d{2})",
                text,
            )

            status_span = td.find(
                "span"
            )

            if (
                not date_match
                or not status_span
            ):
                continue

            title = (
                status_span.get_text(
                    strip=True
                )
            )

            date_str = (
                date_match.group(1)
            )

            lesson_date = (
                datetime.strptime(
                    f"{date_str}/{year}",
                    "%d/%m/%Y",
                )
            )

            start_dt = datetime.strptime(
                f"{lesson_date.date()} {metadata['start_time']}",
                "%Y-%m-%d %I:%M %p",
            )

            end_dt = datetime.strptime(
                f"{lesson_date.date()} {metadata['end_time']}",
                "%Y-%m-%d %I:%M %p",
            )

            lessons.append({
                "child_name":
                    metadata["child_name"],
                "title": title,
                "start":
                    start_dt.isoformat(),
                "end":
                    end_dt.isoformat(),
                "location":
                    metadata["venue"],
            })

        return lessons
