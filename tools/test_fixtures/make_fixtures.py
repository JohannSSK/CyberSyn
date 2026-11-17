#!/usr/bin/env python3
"""Build synthetic test fixtures for the photo scanner.

Everything here is invented data: a generated portrait that exists nowhere,
an AFM that only passes the checksum, a test IBAN. The fixtures exist so the
scanner can be proved end to end without ever touching a real document.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def valid_afm(prefix="094001"):
    """Append the check digits that make `prefix` a valid AFM."""
    base = [int(c) for c in prefix]
    while len(base) < 8:
        base.append(0)
    total = sum(base[i] * (2 ** (8 - i)) for i in range(8))
    check = (total % 11) % 10
    return "".join(str(d) for d in base) + str(check)


def make_id_card():
    card = Image.new("RGB", (1120, 700), (238, 240, 242))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, 1119, 699], outline=(60, 60, 70), width=6)
    d.rectangle([20, 20, 1100, 100], fill=(28, 54, 96))

    f_head = ImageFont.truetype(FONT_B, 34)
    f_label = ImageFont.truetype(FONT, 24)
    f_value = ImageFont.truetype(FONT_B, 30)

    d.text((40, 32), "HELLENIC REPUBLIC - ΔΕΛΤΙΟ ΤΑΥΤΟΤΗΤΑΣ", font=f_head,
           fill=(255, 255, 255))
    d.text((40, 72), "IDENTITY CARD", font=f_label, fill=(200, 210, 225))

    portrait = Image.open(HERE / "portrait.jpg").convert("RGB")
    portrait.thumbnail((300, 420))
    card.paste(portrait, (50, 140))
    d.rectangle([50, 140, 50 + portrait.width, 140 + portrait.height],
                outline=(60, 60, 70), width=3)

    afm = valid_afm()
    fields = [
        ("SURNAME / ΕΠΩΝΥΜΟ", "PAPADOPOULOU"),
        ("NAME / ΟΝΟΜΑ", "MARIA"),
        ("FATHER / ΠΑΤΡΩΝΥΜΟ", "NIKOLAOS"),
        ("ΑΦΜ", afm),
        ("PHONE", "698 123 4567"),
        ("EMAIL", "maria.papadopoulou@example.gr"),
        ("IBAN", "GR16 0110 1250 0000 0001 2300 695"),
        ("ID NO", "AB 123456"),
    ]
    y = 150
    for label, value in fields:
        d.text((420, y), label, font=f_label, fill=(90, 90, 100))
        d.text((420, y + 30), value, font=f_value, fill=(20, 20, 30))
        y += 68

    out = HERE / "id_card.jpg"
    card.save(out, quality=92)
    print("id_card.jpg ->", out, "| AFM:", afm)


def make_delivery_note():
    note = Image.new("RGB", (1000, 760), (252, 252, 250))
    d = ImageDraw.Draw(note)
    f_head = ImageFont.truetype(FONT_B, 40)
    f_text = ImageFont.truetype(FONT, 30)
    d.text((50, 40), "DELIVERY NOTE", font=f_head, fill=(30, 30, 40))
    lines = [
        "Deliver to: MARIA PAPADOPOULOU",
        "12 SOLONOS ST, ATHENS",
        "Contact: 210 364 5789 or +30 697 222 3344",
        "Vehicle plate: ZKA-4821",
        "Card: 4111 1111 1111 1111",
        "AMKA: 01018012345",
        "Ref: ORDER-2026-0042",
    ]
    y = 130
    for line in lines:
        d.text((50, y), line, font=f_text, fill=(35, 35, 45))
        y += 74
    out = HERE / "delivery_note.jpg"
    note.save(out, quality=92)
    print("delivery_note.jpg ->", out)


def make_clean_photo():
    """A landscape with no text and no faces: the negative control."""
    img = Image.new("RGB", (900, 600), (120, 170, 210))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 380, 900, 600], fill=(70, 120, 70))
    d.ellipse([650, 60, 790, 200], fill=(250, 230, 140))
    out = HERE / "clean.jpg"
    img.save(out, quality=90)
    print("clean.jpg ->", out)


if __name__ == "__main__":
    make_id_card()
    make_delivery_note()
    make_clean_photo()
