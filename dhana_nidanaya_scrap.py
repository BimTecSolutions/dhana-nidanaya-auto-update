"""
Dhana Nidhanaya -> Firestore auto updater

Fix note
--------
www.nlb.lk / r.nlb.lk protect their pages with a small JavaScript
cookie challenge. The very first request returns a ~363 byte HTML
stub that contains something like:

    <script>setCookie('xxxxx','yyyyy',10);location.reload();</script>

A real browser runs that script, stores the cookie and reloads, so a
human never notices. `requests` does not run JavaScript, so it kept
receiving the same 363 byte stub forever -> the old script concluded
"draw not available yet".

The fix is to read the cookie out of that stub, put it into the
requests.Session, and repeat the request. After that the real HTML
comes back and parsing works normally.
"""

import os
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


class DhanaNidhanayaAutoUpdater:

    # ============================================================
    # NLB SETTINGS
    # ============================================================

    BASE_URLS = [
        "https://www.nlb.lk",
        "https://r.nlb.lk",
    ]

    LOTTERY_SLUG = "dhana-nidhanaya"
    LOTTERY_NAME = "Dhana Nidhanaya"

    # ============================================================
    # FIRESTORE
    # ============================================================

    FIRESTORE_COLLECTION = "NLB_Results_All"
    FIRESTORE_DOCUMENT = "dhana_nidanaya"
    FIRESTORE_SUBCOLLECTION = "results"

    # ============================================================
    # SETTINGS
    # ============================================================

    MAX_RETRIES = 3
    REQUEST_DELAY = 1.5
    MAX_FORWARD_CHECKS = 10

    # Any response shorter than this that still returns HTTP 200 is
    # almost certainly the JS cookie challenge stub.
    MIN_REAL_PAGE_BYTES = 1000

    def __init__(self, firebase_creds_path: str):

        self.db = None
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nlb.lk/",
            "Connection": "keep-alive",
        })

        self.init_firebase(firebase_creds_path)

    # ============================================================
    # FIREBASE
    # ============================================================

    def init_firebase(self, creds_path):

        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred)

            self.db = firestore.client()
            print("✅ Firebase initialized successfully")

        except Exception as e:
            print(f"❌ Firebase initialization failed: {e}")
            raise

    def get_results_collection(self):

        return (
            self.db
            .collection(self.FIRESTORE_COLLECTION)
            .document(self.FIRESTORE_DOCUMENT)
            .collection(self.FIRESTORE_SUBCOLLECTION)
        )

    def get_firebase_latest_draw(self) -> Optional[int]:

        print("\n🔥 Checking latest Firebase draw...")

        try:
            docs = list(
                self.get_results_collection()
                .order_by(
                    "draw_number",
                    direction=firestore.Query.DESCENDING
                )
                .limit(1)
                .stream()
            )

            if not docs:
                print("⚠️ No Dhana Nidhanaya results found in Firebase.")
                return None

            draw_number = docs[0].to_dict().get("draw_number")

            if draw_number is None:
                print("⚠️ Firebase document does not contain draw_number.")
                return None

            draw_number = int(draw_number)
            print(f"✅ Firebase latest draw: {draw_number}")
            return draw_number

        except Exception as e:
            print(f"❌ Firebase query error: {e}")
            return None

    # ============================================================
    # COOKIE CHALLENGE HANDLING  <-- the actual fix
    # ============================================================

    COOKIE_PATTERNS = [
        # setCookie('name','value',10)
        r"setCookie\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]",
        # document.cookie = "name=value; ..."
        r"document\.cookie\s*=\s*['\"]([^=;'\"]+)=([^;'\"]*)",
    ]

    def looks_like_challenge(self, html: str) -> bool:

        if html is None:
            return False

        if len(html) < self.MIN_REAL_PAGE_BYTES:
            return True

        lowered = html.lower()

        return (
            "setcookie(" in lowered
            and "lresult" not in lowered
        )

    def extract_challenge_cookie(self, html: str):

        for pattern in self.COOKIE_PATTERNS:
            match = re.search(pattern, html)
            if match:
                return match.group(1), match.group(2)

        return None, None

    def solve_challenge(self, url: str, html: str) -> bool:
        """Read the cookie out of the stub page and store it."""

        name, value = self.extract_challenge_cookie(html)

        if not name:
            return False

        domain = urlparse(url).hostname

        self.session.cookies.set(
            name,
            value,
            domain=domain,
            path="/"
        )

        print(f"   🍪 Challenge cookie set for {domain}: {name}")
        return True

    # ============================================================
    # FETCH NLB PAGE
    # ============================================================

    def fetch_page(self, url, retries=None):

        if retries is None:
            retries = self.MAX_RETRIES

        for attempt in range(1, retries + 1):

            try:
                print(f"   🌐 Request {attempt}/{retries}: {url}")

                response = self.session.get(
                    url,
                    timeout=30,
                    allow_redirects=True
                )

                html = response.text

                print(
                    f"   HTTP: {response.status_code} | "
                    f"{len(html)} bytes"
                )

                if response.status_code != 200:
                    raise requests.RequestException(
                        f"HTTP {response.status_code}"
                    )

                # --------------------------------------------
                # Cookie challenge -> solve it and retry once
                # immediately, without burning an attempt.
                # --------------------------------------------
                if self.looks_like_challenge(html):

                    if self.solve_challenge(url, html):

                        time.sleep(0.5)

                        response = self.session.get(
                            url,
                            timeout=30,
                            allow_redirects=True
                        )

                        html = response.text

                        print(
                            f"   HTTP (after cookie): "
                            f"{response.status_code} | "
                            f"{len(html)} bytes"
                        )

                    else:
                        print("   ⚠️ Challenge page but no cookie found.")

                if not self.looks_like_challenge(html):
                    return html

            except Exception as e:
                print(f"   ⚠️ Request error: {e}")

            if attempt < retries:
                time.sleep(2 ** (attempt - 1))

        return None

    def warm_up(self):
        """Visit a normal page once so the cookie is ready up front."""

        print("\n🍪 Warming up NLB session...")

        for base_url in self.BASE_URLS:
            html = self.fetch_page(f"{base_url}/lotteries", retries=2)
            if html:
                print(f"   ✅ Session ready for {base_url}")

    # ============================================================
    # HELPERS
    # ============================================================

    def normalize_text(self, text):

        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def parse_date(self, value):

        if not value:
            return None

        value = value.strip()

        formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%B %d %Y",
            "%b %d, %Y",
            "%b %d %Y",
            "%A, %B %d, %Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).isoformat()
            except ValueError:
                continue

        return value

    # ============================================================
    # PARSE ONE RESULT BLOCK FROM THE REAL HTML
    # ============================================================

    def parse_result_block(self, soup, draw_number):
        """
        NLB result markup looks roughly like:

            <div class="lresult">
              <h1>Dhana Nidhanaya</h1>
              <p>Draw No.: 2341</p>
              <p>Date: 2026-09-15</p>
              <ol class="B">
                <li class="Letter">X</li>
                <li>26</li><li>42</li><li>71</li><li>55</li>
              </ol>
            </div>

        Sunday Bonus, when present, is an extra <ol> in the same block.
        """

        draw_number = str(draw_number)

        blocks = soup.select("div.lresult") or soup.select(".lresult")

        for block in blocks:

            block_text = self.normalize_text(block.get_text(" ", strip=True))

            # Make sure this block is the draw we asked for.
            if not re.search(
                rf"Draw\s*No\.?\s*:?\s*{re.escape(draw_number)}\b",
                block_text,
                re.IGNORECASE
            ):
                continue

            lists = block.select("ol")

            if not lists:
                continue

            main_list = lists[0]

            letter = ""
            numbers = []

            for li in main_list.find_all("li"):

                classes = li.get("class", []) or []

                if "More" in classes:
                    continue

                value = li.get_text(strip=True)

                if not value:
                    continue

                if "Letter" in classes or re.fullmatch(r"[A-Za-z]", value):
                    letter = value.upper()
                elif re.fullmatch(r"\d{1,2}", value):
                    numbers.append(f"{int(value):02d}")

            if len(numbers) < 4:
                continue

            numbers = numbers[:4]

            # ------------------------------------------------
            # Date
            # ------------------------------------------------
            date = None

            date_match = re.search(
                r"Date\s*:?\s*"
                r"(\d{4}-\d{2}-\d{2}"
                r"|\d{1,2}[-/]\d{1,2}[-/]\d{4}"
                r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                block_text,
                re.IGNORECASE
            )

            if date_match:
                date = date_match.group(1).strip()

            # ------------------------------------------------
            # Sunday Bonus (extra <ol>, four single digits)
            # ------------------------------------------------
            bonus = None

            if len(lists) > 1:

                for extra in lists[1:]:

                    digits = [
                        li.get_text(strip=True)
                        for li in extra.find_all("li")
                        if re.fullmatch(r"\d", li.get_text(strip=True) or "")
                    ]

                    if len(digits) >= 4:
                        digits = digits[:4]
                        bonus = {
                            "numbers": digits,
                            "numbers_int": [int(x) for x in digits],
                            "raw_text": self.normalize_text(
                                extra.get_text(" ", strip=True)
                            )[:200],
                        }
                        break

            if bonus is None:
                bonus = self.extract_sunday_bonus_from_text(block_text)

            return {
                "symbol": letter or None,
                "numbers": numbers,
                "date": date,
                "sunday_bonus": bonus,
            }

        return None

    # ============================================================
    # TEXT FALLBACK PARSER
    # ============================================================

    def parse_result_text(self, text, draw_number):

        draw_number = str(draw_number)

        match = re.search(
            rf"Draw\s*No\.?\s*:?\s*{re.escape(draw_number)}\b",
            text,
            re.IGNORECASE
        )

        if not match:
            return None

        section = self.normalize_text(
            text[match.start(): match.start() + 600]
        )

        found = re.search(
            r"\b([A-Z])\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b",
            section
        )

        if not found:
            return None

        numbers = [f"{int(found.group(i)):02d}" for i in range(2, 6)]

        date_match = re.search(
            r"Date\s*:?\s*"
            r"(\d{4}-\d{2}-\d{2}"
            r"|\d{1,2}[-/]\d{1,2}[-/]\d{4}"
            r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            section,
            re.IGNORECASE
        )

        return {
            "symbol": found.group(1).upper(),
            "numbers": numbers,
            "date": date_match.group(1).strip() if date_match else None,
            "sunday_bonus": self.extract_sunday_bonus_from_text(section),
        }

    def extract_sunday_bonus_from_text(self, text):

        text = self.normalize_text(text)

        match = re.search(r"Sunday\s+Bonus", text, re.IGNORECASE)

        if not match:
            return None

        section = text[match.end(): match.end() + 250]

        four_digit = re.search(r"(?<!\d)(\d{4})(?!\d)", section)

        if four_digit:
            digits = list(four_digit.group(1))
            return {
                "numbers": digits,
                "numbers_int": [int(x) for x in digits],
                "raw_text": section[:200],
            }

        digits = re.findall(r"(?<!\d)([0-9])(?!\d)", section)

        if len(digits) >= 4:
            digits = digits[:4]
            return {
                "numbers": digits,
                "numbers_int": [int(x) for x in digits],
                "raw_text": section[:200],
            }

        return None

    # ============================================================
    # FETCH ONE DRAW
    # ============================================================

    def get_result(self, draw_number):

        print(f"\n🔎 Checking draw {draw_number}...")

        urls = []

        for base_url in self.BASE_URLS:
            urls.append(
                f"{base_url}/results/{self.LOTTERY_SLUG}/{draw_number}"
            )

        for url in urls:

            html = self.fetch_page(url)

            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")

            parsed = self.parse_result_block(soup, draw_number)

            if not parsed:
                text = self.normalize_text(
                    soup.get_text(separator=" ", strip=True)
                )
                parsed = self.parse_result_text(text, draw_number)

            if not parsed:
                print("   ⚠️ Draw not found on this page.")
                continue

            result = {
                "lottery": self.LOTTERY_NAME,
                "lottery_slug": self.LOTTERY_SLUG,
                "draw_number": int(draw_number),
                "draw_number_str": str(draw_number),
                "date": parsed["date"],
                "date_iso": self.parse_date(parsed["date"]),
                "symbol": parsed["symbol"],
                "numbers": parsed["numbers"],
                "numbers_int": [int(x) for x in parsed["numbers"]],
                "url": url,
                "scraped_at": datetime.now().isoformat(),
                "source": "National Lotteries Board, Sri Lanka",
            }

            if parsed.get("sunday_bonus"):
                result["sunday_bonus"] = parsed["sunday_bonus"]

            return result

        return None

    # ============================================================
    # UPLOAD
    # ============================================================

    def upload_result(self, result):

        doc_id = f"{self.LOTTERY_SLUG}_{result['draw_number']}"

        try:
            self.get_results_collection().document(doc_id).set(
                result,
                merge=True
            )

            print(f"   ☁️ Firebase upload successful: {doc_id}")
            return True

        except Exception as e:
            print(f"   ❌ Firebase upload failed: {e}")
            return False

    # ============================================================
    # AUTOMATIC UPDATE
    # ============================================================

    def update(self):

        print("\n" + "=" * 75)
        print("🚀 DHANA NIDHANAYA AUTOMATIC UPDATER".center(75))
        print("=" * 75)
        print(f"⏰ Time: {datetime.now().isoformat()}")
        print("\n📁 Firestore: NLB_Results_All/dhana_nidanaya/results")

        firebase_latest = self.get_firebase_latest_draw()

        if firebase_latest is None:
            print("\n❌ Cannot continue. Firebase has no latest draw.")
            return False

        # Solve the cookie challenge once, up front.
        self.warm_up()

        first_draw = firebase_latest + 1

        print("\n" + "-" * 75)
        print(f"🔥 Firebase latest: {firebase_latest}")
        print(f"🔎 Starting NLB check from: {first_draw}")
        print(f"🔎 Maximum forward checks: {self.MAX_FORWARD_CHECKS}")
        print("-" * 75)

        successful = 0
        failed = 0
        bonus_count = 0

        for offset in range(self.MAX_FORWARD_CHECKS):

            draw_number = first_draw + offset

            print("\n" + "-" * 75)
            print(f"📥 Checking draw {draw_number}")

            result = self.get_result(draw_number)

            if not result:
                print(f"   ⏸️ Draw {draw_number} is not available yet.")
                print("   🛑 Stopping future draw search.")
                break

            print(
                f"   🎯 Result: {result['symbol']} "
                f"{' '.join(result['numbers'])}"
            )

            if "sunday_bonus" in result:
                bonus_count += 1
                print(
                    f"   🎁 Sunday Bonus: "
                    f"{' '.join(result['sunday_bonus']['numbers'])}"
                )

            if self.upload_result(result):
                successful += 1
            else:
                failed += 1
                print("   🛑 Stopping because Firebase upload failed.")
                break

            time.sleep(self.REQUEST_DELAY)

        print("\n" + "=" * 75)
        print("📊 UPDATE COMPLETE".center(75))
        print("=" * 75)
        print(f"🔥 Firebase previous latest: {firebase_latest}")
        print(f"🆕 New draws uploaded: {successful}")
        print(f"🎁 Sunday Bonus draws: {bonus_count}")
        print(f"❌ Failed uploads: {failed}")

        if successful == 0:
            print("\nℹ️ No new Dhana Nidhanaya draw was available.")
        else:
            print("\n✅ Firebase has been updated.")

        print("=" * 75)

        return failed == 0

    def close(self):
        self.session.close()


# =================================================================
# MAIN
# =================================================================

def main():

    print("\n" + "=" * 75)
    print("🏆 DHANA NIDHANAYA FIREBASE AUTO UPDATER".center(75))
    print("=" * 75)

    creds_path = os.environ.get(
        "FIREBASE_CREDENTIALS",
        "serviceAccountKey.json"
    )

    print(f"\n🔐 Firebase credentials: {creds_path}")

    if not os.path.exists(creds_path):
        print("\n❌ Firebase credentials file not found.")
        print(f"   Expected: {creds_path}")
        return

    updater = None

    try:
        updater = DhanaNidhanayaAutoUpdater(creds_path)

        if not updater.update():
            raise RuntimeError(
                "Dhana Nidhanaya updater finished with errors."
            )

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise

    finally:
        if updater:
            updater.close()


if __name__ == "__main__":
    main()
