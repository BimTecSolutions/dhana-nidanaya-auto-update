import requests
from bs4 import BeautifulSoup
import re
import time
import json
import os
from typing import Dict, Optional
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore


class DhanaNidhanayaAutoUpdater:

    BASE_URL = "https://www.nlb.lk"

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

    REQUEST_DELAY = 2.0

    # How many recent NLB result pages to check when
    # discovering the latest draw.
    LATEST_SEARCH_LIMIT = 10

    def __init__(
        self,
        firebase_creds_path: str
    ):

        self.db = None

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        })

        self._driver = None

        self.init_firebase(
            firebase_creds_path
        )

    # ============================================================
    # FIREBASE
    # ============================================================

    def init_firebase(
        self,
        creds_path
    ):

        try:

            if not firebase_admin._apps:

                cred = credentials.Certificate(
                    creds_path
                )

                firebase_admin.initialize_app(
                    cred
                )

            self.db = firestore.client()

            print(
                "✅ Firebase initialized successfully"
            )

        except Exception as e:

            print(
                f"❌ Firebase initialization failed: {e}"
            )

            raise

    # ============================================================
    # FIRESTORE REFERENCE
    # ============================================================

    def get_results_collection(self):

        return (
            self.db
            .collection(
                self.FIRESTORE_COLLECTION
            )
            .document(
                self.FIRESTORE_DOCUMENT
            )
            .collection(
                self.FIRESTORE_SUBCOLLECTION
            )
        )

    # ============================================================
    # GET FIREBASE LATEST DRAW
    # ============================================================

    def get_firebase_latest_draw(self) -> Optional[int]:

        print(
            "\n🔥 Checking latest Firebase draw..."
        )

        try:

            docs = (
                self.get_results_collection()
                .order_by(
                    "draw_number",
                    direction=firestore.Query.DESCENDING
                )
                .limit(1)
                .stream()
            )

            docs = list(docs)

            if not docs:

                print(
                    "⚠️ No Dhana Nidhanaya "
                    "results found in Firebase."
                )

                return None

            latest_doc = docs[0]

            data = latest_doc.to_dict()

            draw_number = data.get(
                "draw_number"
            )

            if draw_number is None:

                print(
                    "⚠️ Latest Firebase document "
                    "does not contain draw_number."
                )

                return None

            draw_number = int(
                draw_number
            )

            print(
                f"✅ Firebase latest draw: "
                f"{draw_number}"
            )

            return draw_number

        except Exception as e:

            print(
                f"❌ Firebase latest draw error: {e}"
            )

            return None

    # ============================================================
    # FETCH PAGE
    # ============================================================

    def fetch_page(
        self,
        url,
        retries=None
    ):

        if retries is None:

            retries = self.MAX_RETRIES

        for attempt in range(
            1,
            retries + 1
        ):

            try:

                print(
                    f"   🌐 Request "
                    f"{attempt}/{retries}: "
                    f"{url}"
                )

                response = self.session.get(
                    url,
                    timeout=30
                )

                print(
                    f"   HTTP: "
                    f"{response.status_code} | "
                    f"{len(response.text)} bytes"
                )

                if (
                    response.status_code == 200
                    and len(response.text) > 500
                ):

                    return response.text

            except Exception as e:

                print(
                    f"   ⚠️ Request error: {e}"
                )

            if attempt < retries:

                time.sleep(
                    2 ** (attempt - 1)
                )

        return None

    # ============================================================
    # GET NLB LATEST DRAW
    # ============================================================

    def get_nlb_latest_draw(self) -> Optional[int]:

        print(
            "\n🌐 Checking NLB latest draw..."
        )

        # --------------------------------------------------------
        # First try the NLB results page.
        # --------------------------------------------------------

        candidate_urls = [

            f"{self.BASE_URL}/results/"
            f"{self.LOTTERY_SLUG}",

            f"{self.BASE_URL}/results/"
            f"{self.LOTTERY_SLUG}/",

        ]

        highest_draw = None

        for url in candidate_urls:

            html = self.fetch_page(
                url
            )

            if not html:
                continue

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            text = soup.get_text(
                separator=" ",
                strip=True
            )

            text = self.normalize_text(
                text
            )

            numbers = self.extract_draw_numbers(
                text
            )

            if numbers:

                highest_draw = max(
                    numbers
                )

                print(
                    f"✅ NLB latest draw discovered: "
                    f"{highest_draw}"
                )

                return highest_draw

        # --------------------------------------------------------
        # Fallback:
        #
        # Check recent draw numbers based on
        # Firebase latest draw.
        # --------------------------------------------------------

        firebase_latest = (
            self.get_firebase_latest_draw()
        )

        if firebase_latest:

            start = (
                firebase_latest
                + 1
            )

            end = (
                firebase_latest
                + self.LATEST_SEARCH_LIMIT
            )

            print(
                f"🔎 Checking possible new draws "
                f"{start} → {end}"
            )

            found = []

            for draw in range(
                start,
                end + 1
            ):

                url = (
                    f"{self.BASE_URL}/results/"
                    f"{self.LOTTERY_SLUG}/"
                    f"{draw}"
                )

                html = self.fetch_page(
                    url,
                    retries=1
                )

                if not html:
                    continue

                soup = BeautifulSoup(
                    html,
                    "html.parser"
                )

                text = soup.get_text(
                    separator=" ",
                    strip=True
                )

                if self.find_draw_number(
                    text,
                    str(draw)
                ):

                    found.append(
                        draw
                    )

                time.sleep(
                    0.5
                )

            if found:

                highest_draw = max(
                    found
                )

                print(
                    f"✅ NLB latest draw: "
                    f"{highest_draw}"
                )

                return highest_draw

        print(
            "❌ Could not determine "
            "NLB latest draw."
        )

        return None

    # ============================================================
    # EXTRACT DRAW NUMBERS
    # ============================================================

    def extract_draw_numbers(
        self,
        text
    ):

        numbers = set()

        patterns = [

            r"(?:Draw|Lottery)"
            r"\s*(?:No|Number)?\.?"
            r"\s*:?\s*(\d{3,6})",

            r"\bNo\.?\s*(\d{3,6})\b",

        ]

        for pattern in patterns:

            matches = re.findall(
                pattern,
                text,
                re.IGNORECASE
            )

            for value in matches:

                try:

                    number = int(value)

                    if number >= 100:

                        numbers.add(
                            number
                        )

                except:

                    pass

        return numbers

    # ============================================================
    # NORMALIZE TEXT
    # ============================================================

    def normalize_text(
        self,
        text
    ):

        text = text.replace(
            "\xa0",
            " "
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    # ============================================================
    # FIND DRAW NUMBER
    # ============================================================

    def find_draw_number(
        self,
        text,
        draw_number
    ):

        patterns = [

            rf"\bDraw\s*(?:No|Number)?\.?\s*:?\s*"
            rf"{re.escape(draw_number)}\b",

            rf"\bLottery\s*(?:No|Number)?\.?\s*:?\s*"
            rf"{re.escape(draw_number)}\b",

            rf"\bNo\.?\s*{re.escape(draw_number)}\b",

            rf"\b{re.escape(draw_number)}\b",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                return match

        return None

    # ============================================================
    # EXTRACT NORMAL RESULT
    # ============================================================

    def extract_normal_result(
        self,
        text,
        draw_number
    ):

        result = {

            "found": False,

            "symbol": None,

            "numbers": []

        }

        match = self.find_draw_number(
            text,
            draw_number
        )

        if match:

            start = max(
                0,
                match.start() - 300
            )

            end = min(
                len(text),
                match.end() + 1200
            )

            area = text[
                start:end
            ]

        else:

            area = text

        area = self.normalize_text(
            area
        )

        patterns = [

            r"\b([A-Z])\s+"
            r"(\d{1,2})\s+"
            r"(\d{1,2})\s+"
            r"(\d{1,2})\s+"
            r"(\d{1,2})\b",

            r"\b([A-Z])\s*"
            r"(\d{1,2})\s*"
            r"(\d{1,2})\s*"
            r"(\d{1,2})\s*"
            r"(\d{1,2})\b",

        ]

        for pattern in patterns:

            matches = re.findall(
                pattern,
                area,
                re.IGNORECASE
            )

            for item in matches:

                symbol = item[0].upper()

                numbers = []

                for value in item[1:]:

                    try:

                        number = int(value)

                        if 0 <= number <= 99:

                            numbers.append(
                                number
                            )

                    except:

                        pass

                if len(numbers) >= 4:

                    result["found"] = True

                    result["symbol"] = symbol

                    result["numbers"] = [
                        f"{x:02d}"
                        for x in numbers[:4]
                    ]

                    return result

        return result

    # ============================================================
    # SUNDAY BONUS
    # ============================================================

    def extract_sunday_bonus(
        self,
        text
    ):

        text = self.normalize_text(
            text
        )

        keyword = re.search(
            r"Sunday\s+Bonus"
            r"(?:\s+Draw)?",
            text,
            re.IGNORECASE
        )

        if not keyword:

            return None

        section = text[
            keyword.end():
            keyword.end() + 300
        ]

        # --------------------------------------------------------
        # Four separate digits
        # --------------------------------------------------------

        digits = re.findall(
            r"(?<!\d)([0-9])(?!\d)",
            section
        )

        if len(digits) >= 4:

            digits = digits[:4]

            return {

                "numbers": digits,

                "numbers_int": [
                    int(x)
                    for x in digits
                ],

                "raw_text":
                    section[:200]

            }

        # --------------------------------------------------------
        # Four-digit number
        # --------------------------------------------------------

        match = re.search(
            r"(?<!\d)(\d{4})(?!\d)",
            section
        )

        if match:

            value = match.group(1)

            digits = list(
                value
            )

            return {

                "numbers": digits,

                "numbers_int": [
                    int(x)
                    for x in digits
                ],

                "raw_text":
                    section[:200]

            }

        return None

    # ============================================================
    # DATE
    # ============================================================

    def extract_date(
        self,
        text
    ):

        patterns = [

            r"(?:Draw\s+Date|Date)"
            r"\s*:?\s*"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",

            r"\b"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})"
            r"\b"

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                return match.group(1)

        return None

    # ============================================================
    # PARSE DATE
    # ============================================================

    def parse_date(
        self,
        value
    ):

        if not value:

            return None

        formats = [

            "%B %d, %Y",

            "%B %d %Y",

            "%b %d, %Y",

            "%b %d %Y"

        ]

        for fmt in formats:

            try:

                return datetime.strptime(
                    value.strip(),
                    fmt
                ).isoformat()

            except:

                continue

        return value

    # ============================================================
    # GET COMPLETE DRAW RESULT
    # ============================================================

    def get_result(
        self,
        draw_number
    ):

        urls = [

            (
                f"{self.BASE_URL}/results/"
                f"{self.LOTTERY_SLUG}/"
                f"{draw_number}"
            ),

            (
                f"{self.BASE_URL}/results/"
                f"{self.LOTTERY_SLUG}/"
                f"{draw_number}/"
            ),

            (
                f"{self.BASE_URL}/lottery/"
                f"{self.LOTTERY_SLUG}/results/"
                f"{draw_number}"
            ),

        ]

        for url in urls:

            html = self.fetch_page(
                url
            )

            if not html:

                continue

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            text = soup.get_text(
                separator=" ",
                strip=True
            )

            text = self.normalize_text(
                text
            )

            normal = (
                self.extract_normal_result(
                    text,
                    str(draw_number)
                )
            )

            bonus = (
                self.extract_sunday_bonus(
                    text
                )
            )

            # ----------------------------------------------------
            # Normal result
            # ----------------------------------------------------

            if normal["found"]:

                date = self.extract_date(
                    text
                )

                result = {

                    "lottery":
                        self.LOTTERY_NAME,

                    "lottery_slug":
                        self.LOTTERY_SLUG,

                    "draw_number":
                        int(draw_number),

                    "draw_number_str":
                        str(draw_number),

                    "date":
                        date,

                    "date_iso":
                        self.parse_date(
                            date
                        ),

                    "symbol":
                        normal["symbol"],

                    "numbers":
                        normal["numbers"],

                    "numbers_int":
                        [
                            int(x)
                            for x in normal["numbers"]
                        ],

                    "url":
                        url,

                    "scraped_at":
                        datetime.now().isoformat(),

                    "source":
                        "National Lotteries Board, Sri Lanka"

                }

                # ------------------------------------------------
                # Sunday Bonus only when present
                # ------------------------------------------------

                if bonus:

                    result[
                        "sunday_bonus"
                    ] = bonus

                return result

        return None

    # ============================================================
    # FIRESTORE UPLOAD
    # ============================================================

    def upload_result(
        self,
        result
    ):

        draw_number = (
            result["draw_number"]
        )

        doc_id = (
            f"{self.LOTTERY_SLUG}_"
            f"{draw_number}"
        )

        try:

            doc_ref = (
                self.get_results_collection()
                .document(
                    doc_id
                )
            )

            doc_ref.set(
                result,
                merge=True
            )

            print(
                f"   ☁️ Uploaded Firebase: "
                f"{doc_id}"
            )

            return True

        except Exception as e:

            print(
                f"   ❌ Firebase upload error: "
                f"{e}"
            )

            return False

    # ============================================================
    # MAIN UPDATE
    # ============================================================

    def update(self):

        print(
            "\n" + "=" * 75
        )

        print(
            "🚀 DHANA NIDHANAYA "
            "AUTOMATIC UPDATER"
            .center(75)
        )

        print(
            "=" * 75
        )

        print(
            f"⏰ Time: "
            f"{datetime.now().isoformat()}"
        )

        print(
            "\n📁 Firestore:"
        )

        print(
            "   NLB_Results_All/"
            "dhana_nidanaya/results"
        )

        # ========================================================
        # FIREBASE LATEST
        # ========================================================

        firebase_latest = (
            self.get_firebase_latest_draw()
        )

        # ========================================================
        # NLB LATEST
        # ========================================================

        nlb_latest = (
            self.get_nlb_latest_draw()
        )

        if nlb_latest is None:

            print(
                "\n❌ Could not determine "
                "NLB latest draw."
            )

            return False

        # ========================================================
        # FIRST RUN
        # ========================================================

        if firebase_latest is None:

            print(
                "\n⚠️ Firebase contains "
                "no Dhana Nidhanaya results."
            )

            print(
                "⚠️ Please seed the database "
                "with historical results first."
            )

            return False

        # ========================================================
        # COMPARE
        # ========================================================

        print(
            "\n" + "-" * 75
        )

        print(
            f"🔥 Firebase latest: "
            f"{firebase_latest}"
        )

        print(
            f"🌐 NLB latest: "
            f"{nlb_latest}"
        )

        print(
            "-" * 75
        )

        # ========================================================
        # NO UPDATE
        # ========================================================

        if nlb_latest <= firebase_latest:

            print(
                "\n✅ Firebase is already up to date."
            )

            print(
                f"   No new draw found."
            )

            return True

        # ========================================================
        # NEW DRAW(S)
        # ========================================================

        first_missing = (
            firebase_latest + 1
        )

        last_missing = nlb_latest

        total_missing = (
            last_missing
            - first_missing
            + 1
        )

        print(
            f"\n🆕 New draw(s) detected!"
        )

        print(
            f"📥 Missing range: "
            f"{first_missing} → "
            f"{last_missing}"
        )

        print(
            f"📊 Number of missing draws: "
            f"{total_missing}"
        )

        successful = 0

        failed = 0

        bonus_count = 0

        # ========================================================
        # FETCH EACH MISSING DRAW
        # ========================================================

        for draw in range(
            first_missing,
            last_missing + 1
        ):

            print(
                "\n" + "-" * 75
            )

            print(
                f"📥 Processing draw "
                f"{draw}"
            )

            result = None

            for attempt in range(
                1,
                self.MAX_RETRIES + 1
            ):

                print(
                    f"   Attempt "
                    f"{attempt}/"
                    f"{self.MAX_RETRIES}"
                )

                result = self.get_result(
                    draw
                )

                if result:

                    break

                if attempt < self.MAX_RETRIES:

                    wait = (
                        2 ** (attempt - 1)
                    )

                    print(
                        f"   ⏳ Waiting "
                        f"{wait}s before retry..."
                    )

                    time.sleep(
                        wait
                    )

            # ----------------------------------------------------
            # FAILED
            # ----------------------------------------------------

            if not result:

                failed += 1

                print(
                    f"   ❌ Could not fetch "
                    f"draw {draw}"
                )

                continue

            # ----------------------------------------------------
            # DISPLAY
            # ----------------------------------------------------

            normal_numbers = " ".join(
                result["numbers"]
            )

            print(
                f"   🎯 Result: "
                f"{result['symbol']} "
                f"{normal_numbers}"
            )

            # ----------------------------------------------------
            # SUNDAY BONUS
            # ----------------------------------------------------

            if "sunday_bonus" in result:

                bonus_count += 1

                bonus_numbers = " ".join(
                    result[
                        "sunday_bonus"
                    ]["numbers"]
                )

                print(
                    f"   🎁 Sunday Bonus: "
                    f"{bonus_numbers}"
                )

            # ----------------------------------------------------
            # UPLOAD
            # ----------------------------------------------------

            if self.upload_result(
                result
            ):

                successful += 1

            else:

                failed += 1

            # ----------------------------------------------------
            # DELAY
            # ----------------------------------------------------

            if draw < last_missing:

                time.sleep(
                    self.REQUEST_DELAY
                )

        # ========================================================
        # SUMMARY
        # ========================================================

        print(
            "\n" + "=" * 75
        )

        print(
            "📊 UPDATE COMPLETE"
            .center(75)
        )

        print(
            "=" * 75
        )

        print(
            f"🔥 Previous Firebase latest: "
            f"{firebase_latest}"
        )

        print(
            f"🌐 NLB latest: "
            f"{nlb_latest}"
        )

        print(
            f"📥 Missing draws: "
            f"{total_missing}"
        )

        print(
            f"✅ Successfully uploaded: "
            f"{successful}"
        )

        print(
            f"🎁 Sunday Bonus draws: "
            f"{bonus_count}"
        )

        print(
            f"❌ Failed: "
            f"{failed}"
        )

        print(
            "=" * 75
        )

        return failed == 0

    # ============================================================
    # CLOSE
    # ============================================================

    def close(self):

        if self._driver:

            try:

                self._driver.quit()

            except:

                pass

            self._driver = None


# =================================================================
# MAIN
# =================================================================

def main():

    print(
        "\n" + "=" * 75
    )

    print(
        "🏆 DHANA NIDHANAYA "
        "FIREBASE AUTO UPDATER"
        .center(75)
    )

    print(
        "=" * 75
    )

    # ------------------------------------------------------------
    # GitHub Actions will provide this environment variable.
    #
    # For local testing you can still use:
    #
    # export FIREBASE_CREDENTIALS=./serviceAccountKey.json
    # ------------------------------------------------------------

    creds_path = os.environ.get(
        "FIREBASE_CREDENTIALS"
    )

    if not creds_path:

        # Local fallback
        creds_path = "serviceAccountKey.json"

    if not os.path.exists(
        creds_path
    ):

        print(
            f"❌ Firebase credentials file "
            f"not found:"
        )

        print(
            f"   {creds_path}"
        )

        print(
            "\nFor GitHub Actions, make sure "
            "the workflow creates this file."
        )

        return

    updater = None

    try:

        updater = DhanaNidhanayaAutoUpdater(
            creds_path
        )

        updater.update()

    except Exception as e:

        print(
            f"\n❌ Fatal error: {e}"
        )

        raise

    finally:

        if updater:

            updater.close()


if __name__ == "__main__":

    main()

