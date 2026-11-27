#!/usr/bin/env python3
"""
rank_gulf_winners.py
Reads raw product exports (JSON or CSV) from ./raw across Gulf marketplaces
(Amazon SA, Noon, Shein, Trendyol), normalizes prices to SAR, computes a weighted
winner_score, tracks rank_change vs previous run, and outputs:
  - gulf_top_100_winners.json
  - gulf_top_100_winners.csv
"""

import argparse
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

PRICE_TO_SAR = {
    "SAR": 1.0,
    "AED": 1.02,
    "KWD": 12.2,
    "QAR": 1.03,
    "BHD": 9.95,
    "OMR": 9.74,
    "TRY": 0.11,
    "USD": 3.75,
}

PLATFORM_RATES = {
    "Amazon SA": 1.0,
    "Noon": 1.0,
    "Shein": 1.0,
    "Trendyol": 0.11,
}

WEIGHTS = {
    "rank": 0.30,
    "rating": 0.25,
    "reviews": 0.25,
    "discount": 0.20,
}


def parse_number(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^0-9.\-]", "", str(val))
    try:
        return float(cleaned) if cleaned else default
    except ValueError:
        return default


def normalize_platform(raw_platform):
    p = str(raw_platform or "Amazon SA").strip().lower()
    if "amazon" in p:
        return "Amazon SA"
    if "noon" in p:
        return "Noon"
    if "shein" in p:
        return "Shein"
    if "trendyol" in p:
        return "Trendyol"
    return raw_platform or "Amazon SA"


def load_raw_records(input_dir: Path):
    records = []
    if not input_dir.exists():
        return records

    for file_path in sorted(input_dir.iterdir()):
        if file_path.suffix.lower() == ".json":
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    records.extend(data)
                elif isinstance(data, dict):
                    for key in ("products", "items", "data", "results"):
                        if isinstance(data.get(key), list):
                            records.extend(data[key])
                            break
            except Exception as exc:
                print(f"Skipping {file_path.name}: {exc}")
        elif file_path.suffix.lower() == ".csv":
            try:
                with file_path.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    records.extend(list(reader))
            except Exception as exc:
                print(f"Skipping {file_path.name}: {exc}")
    return records


def score_products(records, prev_ranks):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scored = []
    seen_titles = set()

    for idx, item in enumerate(records, start=1):
        title = str(
            item.get("title")
            or item.get("name")
            or item.get("product_name")
            or f"Gulf Product #{idx}"
        ).strip()
        key = re.sub(r"\W+", " ", title.lower()).strip()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)

        platform = normalize_platform(item.get("platform") or item.get("source"))
        category = str(item.get("category") or "Trending").strip()
        raw_rank = int(parse_number(item.get("rank"), idx))
        if raw_rank <= 0:
            raw_rank = idx

        rating = min(5.0, max(0.0, parse_number(item.get("rating"), 4.6)))
        reviews = int(max(0, parse_number(item.get("reviews") or item.get("review_count"), 150)))

        currency = str(item.get("currency") or "").strip().upper()
        rate = PRICE_TO_SAR.get(currency, PLATFORM_RATES.get(platform, 1.0))

        price_raw = parse_number(item.get("price_sar") or item.get("price"), 59.0)
        if item.get("price_sar") is not None and currency in ("", "SAR"):
            price_sar = round(price_raw, 2)
        else:
            price_sar = round(price_raw * rate, 2)

        orig_raw = parse_number(item.get("original_price_sar") or item.get("original_price"), 0.0)
        if orig_raw > 0:
            orig_sar = round(orig_raw * (1.0 if item.get("original_price_sar") else rate), 2)
        else:
            orig_sar = round(price_sar * 1.35, 2)

        if orig_sar < price_sar:
            orig_sar = price_sar

        discount_pct = int(round(((orig_sar - price_sar) / orig_sar) * 100)) if orig_sar > 0 else 0

        # Component scores (0-100 scale)
        rank_score = max(10.0, 100.0 - (raw_rank - 1) * 4.5)
        rating_score = (rating / 5.0) * 100.0
        review_score = min(100.0, (math.log10(reviews + 1) / 4.0) * 100.0)
        discount_score = min(100.0, discount_pct * 1.8)

        winner_score = round(
            rank_score * WEIGHTS["rank"]
            + rating_score * WEIGHTS["rating"]
            + review_score * WEIGHTS["reviews"]
            + discount_score * WEIGHTS["discount"],
            1,
        )

        scored.append(
            {
                "title": title,
                "platform": platform,
                "category": category,
                "rating": round(rating, 1),
                "reviews": reviews,
                "price_sar": price_sar,
                "original_price_sar": orig_sar,
                "discount_pct": discount_pct,
                "winner_score": winner_score,
                "bestseller_tag": f"#{raw_rank} in {category}",
                "image_url": str(item.get("image_url") or item.get("image") or "").strip(),
                "product_url": str(item.get("product_url") or item.get("url") or "").strip(),
                "insight": str(
                    item.get("insight")
                    or f"Strong demand on {platform} with {discount_pct}% savings and {rating:.1f}★ rating."
                ).strip(),
                "updated_at": now_iso,
            }
        )

    scored.sort(key=lambda x: (-x["winner_score"], -x["reviews"]))
    top_100 = scored[:100]

    for final_rank, prod in enumerate(top_100, start=1):
        prod["rank"] = final_rank
        prev = prev_ranks.get(prod["title"].lower())
        if prev is None:
            prod["rank_change"] = 0
            prod["is_new"] = True
        else:
            prod["rank_change"] = prev - final_rank
            prod["is_new"] = False

    return top_100


def main():
    parser = argparse.ArgumentParser(description="Rank top Gulf e-commerce winning products.")
    parser.add_argument("--input-dir", default="raw", help="Directory containing raw JSON/CSV exports")
    parser.add_argument("--out-dir", default=".", help="Output directory for JSON and CSV")
    parser.add_argument("--download-images", action="store_true", help="Optional flag compatibility")
    parser.add_argument("--image-base-url", default="", help="Optional base URL compatibility")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "gulf_top_100_winners.json"
    csv_path = out_dir / "gulf_top_100_winners.csv"

    prev_ranks = {}
    if json_path.exists():
        try:
            old_data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(old_data, list):
                for row in old_data:
                    if row.get("title") and row.get("rank"):
                        prev_ranks[str(row["title"]).lower()] = int(row["rank"])
        except Exception:
            pass

    records = load_raw_records(input_dir)
    top_products = score_products(records, prev_ranks)

    json_path.write_text(json.dumps(top_products, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = [
        "rank",
        "rank_change",
        "is_new",
        "title",
        "platform",
        "category",
        "price_sar",
        "original_price_sar",
        "discount_pct",
        "rating",
        "reviews",
        "winner_score",
        "bestseller_tag",
        "product_url",
        "insight",
        "updated_at",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(top_products)

    print(f"Scored {len(records)} raw listings -> wrote Top {len(top_products)} winners to {json_path}")


if __name__ == "__main__":
    main()
