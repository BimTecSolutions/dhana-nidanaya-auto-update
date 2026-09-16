import requests
from bs4 import BeautifulSoup
import re
import time
import os
from typing import Dict, Optional
from datetime import datetime

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

    # Maximum number of future draw numbers to check
    # in one workflow execution.
    MAX_FORWARD_CHECKS = 10

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
                "image/avif,image/webp,"
                "image/apng,*/*;q=0.8"
            ),

            "Accept-Language":
                "en-US,en;q=0.9",

            "Referer":
                "https://www.nlb.lk/",

            "Connection":
                "keep-alive",

        })

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
    # FIRESTORE COLLECTION
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

    def get_firebase_latest_draw(
        self
    ) -> Optional[int]:

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

            data = docs[0].to_dict()

            draw_number = data.get(
                "draw_number"
            )

            if draw_number is None:

                print(
                    "⚠️ Firebase document does not "
                    "contain draw_number."
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
                f"❌ Firebase query error: {e}"
            )

            return None

    # ============================================================
    # FETCH NLB PAGE
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
                    timeout=30,
                    allow_redirects=True
                )

                print(
                    f"   HTTP: "
                    f"{response.status_code} | "
                    f"{len(response.text)} bytes"
                )

                # ------------------------------------------------
                # Important:
                #
                # The old GitHub request was returning only
                # approximately 363 bytes.
                #
                # We don't consider that a valid result page.
                # ------------------------------------------------

                if (
                    response.status_code == 200
                    and len(response.text) > 1000
                ):

                    return response.text

                # Sometimes a valid page may be slightly smaller,
                # but the 363-byte response observed in GitHub
                # should definitely not be accepted.

                if (
                    response.status_code == 200
                    and "Draw No." in response.text
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
    # FIND DRAW NUMBER
    # ============================================================

    def find_draw_number(
        self,
        text,
        draw_number
    ):

        draw_number = str(
            draw_number
        )

        patterns = [

            rf"Draw\s*No\.?\s*:?\s*"
            rf"{re.escape(draw_number)}\b",

            rf"Latest\s+Results?\s*:?\s*"
            rf"{re.escape(draw_number)}\b",

            rf"\b"
            rf"{re.escape(draw_number)}"
            rf"\b",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                return True

        return False

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
    # EXTRACT DRAW DATE
    # ============================================================

    def extract_date(
        self,
        text
    ):

        patterns = [

            r"Draw\s+Date\s*:?\s*"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",

            r"Date\s*:?\s*"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",

            r"\b"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})"
            r"\b",

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
            "%b %d %Y",

        ]

        for fmt in formats:

            try:

                dt = datetime.strptime(
                    value.strip(),
                    fmt
                )

                return dt.isoformat()

            except:

                continue

        return value

    # ============================================================
    # EXTRACT NORMAL WINNING NUMBERS
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

        draw_number = str(
            draw_number
        )

        # --------------------------------------------------------
        # Find the draw number and inspect nearby content.
        # --------------------------------------------------------

        match = re.search(
            rf"Draw\s*No\.?\s*:?\s*"
            rf"{re.escape(draw_number)}",
            text,
            re.IGNORECASE
        )

        if match:

            start = max(
                0,
                match.start() - 100
            )

            end = min(
                len(text),
                match.end() + 800
            )

            section = text[
                start:end
            ]

        else:

            section = text

        section = self.normalize_text(
            section
        )

        # --------------------------------------------------------
        # Standard Dhana Nidhanaya format:
        #
        # Letter + 4 numbers
        #
        # Example:
        #
        # U 04 36 49 72
        # --------------------------------------------------------

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
                section,
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

                if len(numbers) == 4:

                    result["found"] = True

                    result["symbol"] = symbol

                    result["numbers"] = [

                        f"{number:02d}"

                        for number in numbers

                    ]

                    return result

        return result

    # ============================================================
    # EXTRACT SUNDAY BONUS
    # ============================================================

    def extract_sunday_bonus(
        self,
        text
    ):

        text = self.normalize_text(
            text
        )

        # --------------------------------------------------------
        # Find "Sunday Bonus"
        # --------------------------------------------------------

        match = re.search(
            r"Sunday\s+Bonus",
            text,
            re.IGNORECASE
        )

        if not match:

            return None

        # --------------------------------------------------------
        # Only inspect a small area immediately after
        # "Sunday Bonus".
        # --------------------------------------------------------

        section = text[
            match.end():
            match.end() + 250
        ]

        # --------------------------------------------------------
        # Look for a four-digit standalone number first.
        #
        # Example:
        #
        # 1985
        # --------------------------------------------------------

        four_digit = re.search(
            r"(?<!\d)(\d{4})(?!\d)",
            section
        )

        if four_digit:

            value = four_digit.group(1)

            digits = list(
                value
            )

            return {

                "numbers":
                    digits,

                "numbers_int": [
                    int(x)
                    for x in digits
                ],

                "raw_text":
                    section[:200]

            }

        # --------------------------------------------------------
        # Otherwise find four individual digits.
        # --------------------------------------------------------

        digits = re.findall(
            r"(?<!\d)([0-9])(?!\d)",
            section
        )

        if len(digits) >= 4:

            digits = digits[:4]

            return {

                "numbers":
                    digits,

                "numbers_int": [
                    int(x)
                    for x in digits
                ],

                "raw_text":
                    section[:200]

            }

        return None

    # ============================================================
    # FETCH ONE DRAW
    # ============================================================

    def get_result(
        self,
        draw_number
    ):

        print(
            f"\n🔎 Checking draw "
            f"{draw_number}..."
        )

        # --------------------------------------------------------
        # Try both NLB domains.
        # --------------------------------------------------------

        urls = []

        for base_url in self.BASE_URLS:

            urls.extend([

                (
                    f"{base_url}/results/"
                    f"{self.LOTTERY_SLUG}/"
                    f"{draw_number}"
                ),

                (
                    f"{base_url}/results/"
                    f"{self.LOTTERY_SLUG}/"
                    f"{draw_number}/"
                ),

            ])

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

            # ----------------------------------------------------
            # Verify that this is really the requested draw.
            # ----------------------------------------------------

            if not self.find_draw_number(
                text,
                draw_number
            ):

                print(
                    "   ⚠️ Draw number not "
                    "found on page."
                )

                continue

            # ----------------------------------------------------
            # Extract normal result.
            # ----------------------------------------------------

            normal = (
                self.extract_normal_result(
                    text,
                    draw_number
                )
            )

            if not normal["found"]:

                print(
                    "   ⚠️ Normal winning "
                    "numbers not found."
                )

                continue

            # ----------------------------------------------------
            # Extract date.
            # ----------------------------------------------------

            date = self.extract_date(
                text
            )

            # ----------------------------------------------------
            # Build result.
            # ----------------------------------------------------

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

            # ----------------------------------------------------
            # Sunday Bonus
            # ----------------------------------------------------

            bonus = (
                self.extract_sunday_bonus(
                    text
                )
            )

            if bonus:

                result[
                    "sunday_bonus"
                ] = bonus

            return result

        return None

    # ============================================================
    # UPLOAD TO FIRESTORE
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
                f"   ☁️ Firebase upload successful:"
            )

            print(
                f"      {doc_id}"
            )

            return True

        except Exception as e:

            print(
                f"   ❌ Firebase upload failed:"
                f" {e}"
            )

            return False

    # ============================================================
    # AUTOMATIC UPDATE
    # ============================================================

    def update(
        self
    ):

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
        # STEP 1
        # ========================================================

        firebase_latest = (
            self.get_firebase_latest_draw()
        )

        if firebase_latest is None:

            print(
                "\n❌ Cannot continue."
            )

            print(
                "Firebase does not contain "
                "a latest draw."
            )

            return False

        # ========================================================
        # STEP 2
        #
        # Instead of asking NLB for its latest draw,
        # start checking immediately after Firebase.
        # ========================================================

        first_draw = (
            firebase_latest + 1
        )

        print(
            "\n" + "-" * 75
        )

        print(
            f"🔥 Firebase latest: "
            f"{firebase_latest}"
        )

        print(
            f"🔎 Starting NLB check from: "
            f"{first_draw}"
        )

        print(
            f"🔎 Maximum forward checks: "
            f"{self.MAX_FORWARD_CHECKS}"
        )

        print(
            "-" * 75
        )

        successful = 0

        failed = 0

        bonus_count = 0

        consecutive_missing = 0

        # ========================================================
        # CHECK FUTURE DRAWS
        # ========================================================

        for offset in range(
            self.MAX_FORWARD_CHECKS
        ):

            draw_number = (
                first_draw + offset
            )

            print(
                "\n" + "-" * 75
            )

            print(
                f"📥 Checking draw "
                f"{draw_number}"
            )

            result = None

            # ----------------------------------------------------
            # Retry fetching the draw.
            # ----------------------------------------------------

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
                    draw_number
                )

                if result:

                    break

                if attempt < self.MAX_RETRIES:

                    wait = (
                        2 ** (attempt - 1)
                    )

                    print(
                        f"   ⏳ Waiting "
                        f"{wait}s..."
                    )

                    time.sleep(
                        wait
                    )

            # ----------------------------------------------------
            # Draw does not exist yet.
            #
            # We stop here because draw numbers are sequential.
            # ----------------------------------------------------

            if not result:

                consecutive_missing += 1

                print(
                    f"   ⏸️ Draw {draw_number} "
                    f"is not available yet."
                )

                print(
                    "   🛑 Stopping future "
                    "draw search."
                )

                break

            # ----------------------------------------------------
            # Reset missing counter.
            # ----------------------------------------------------

            consecutive_missing = 0

            # ----------------------------------------------------
            # Display normal result.
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
            # Sunday Bonus.
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
            # Upload.
            # ----------------------------------------------------

            if self.upload_result(
                result
            ):

                successful += 1

            else:

                failed += 1

                # If upload fails, stop.
                #
                # This prevents us from uploading later draws
                # while an earlier draw is missing.

                print(
                    "   🛑 Stopping because "
                    "Firebase upload failed."
                )

                break

            # ----------------------------------------------------
            # Delay before next draw.
            # ----------------------------------------------------

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
            f"🔥 Firebase previous latest: "
            f"{firebase_latest}"
        )

        print(
            f"🆕 New draws uploaded: "
            f"{successful}"
        )

        print(
            f"🎁 Sunday Bonus draws: "
            f"{bonus_count}"
        )

        print(
            f"❌ Failed uploads: "
            f"{failed}"
        )

        if successful == 0:

            print(
                "\nℹ️ No new Dhana Nidhanaya "
                "draw was available."
            )

        else:

            print(
                "\n✅ Firebase has been updated."
            )

        print(
            "=" * 75
        )

        return failed == 0

    # ============================================================
    # CLOSE
    # ============================================================

    def close(
        self
    ):

        pass


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
    # GitHub Actions:
    #
    # FIREBASE_CREDENTIALS=serviceAccountKey.json
    #
    # Local:
    #
    # serviceAccountKey.json
    # ------------------------------------------------------------

    creds_path = os.environ.get(
        "FIREBASE_CREDENTIALS",
        "serviceAccountKey.json"
    )

    print(
        f"\n🔐 Firebase credentials: "
        f"{creds_path}"
    )

    if not os.path.exists(
        creds_path
    ):

        print(
            "\n❌ Firebase credentials "
            "file not found."
        )

        print(
            f"   Expected: {creds_path}"
        )

        return

    updater = None

    try:

        updater = (
            DhanaNidhanayaAutoUpdater(
                creds_path
            )
        )

        success = updater.update()

        if not success:

            raise RuntimeError(
                "Dhana Nidhanaya updater "
                "finished with errors."
            )

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
