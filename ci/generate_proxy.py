#!/usr/bin/env python3
"""Generate the private build-time MTProto header without printing secrets."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
from pathlib import Path


def read_value(name: str) -> str:
    value = os.environ.get(name, "")
    if any(character in value for character in ("\0", "\r", "\n")):
        raise SystemExit(f"{name} contains a forbidden control character.")
    if value != value.strip():
        raise SystemExit(f"{name} must not start or end with whitespace.")
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def normalize_mtproto_secret(value: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
        raw = bytes.fromhex(value)
        normalized = value
    else:
        normalized = value.replace("+", "-").replace("/", "_")
        if not re.fullmatch(r"[0-9A-Za-z_-]+={0,2}", normalized):
            raise SystemExit("PRECONFIGURED_PROXY_SECRET is not hexadecimal or Base64URL.")
        try:
            padding = "=" * (-len(normalized.rstrip("=")) % 4)
            raw = base64.urlsafe_b64decode(normalized.rstrip("=") + padding)
        except (ValueError, binascii.Error) as error:
            raise SystemExit("PRECONFIGURED_PROXY_SECRET is not valid Base64URL.") from error

    valid = (
        len(raw) == 16
        or (len(raw) == 17 and raw[0] == 0xDD)
        or (len(raw) >= 21 and raw[0] == 0xEE)
    )
    if not valid:
        raise SystemExit(
            "PRECONFIGURED_PROXY_SECRET has a length or prefix unsupported by Telegram Desktop."
        )
    return raw.hex()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    host = read_value("PRECONFIGURED_PROXY_HOST")
    if "://" in host or any(c.isspace() for c in host):
        raise SystemExit("PRECONFIGURED_PROXY_HOST must be only a hostname or IP, without a URL scheme or spaces.")

    port_text = read_value("PRECONFIGURED_PROXY_PORT")
    if not port_text.isascii() or not port_text.isdecimal():
        raise SystemExit("PRECONFIGURED_PROXY_PORT must contain digits only.")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise SystemExit("PRECONFIGURED_PROXY_PORT must be between 1 and 65535.")

    secret = normalize_mtproto_secret(read_value("PRECONFIGURED_PROXY_SECRET"))

    contents = f"""/*
This file is part of Telegram Desktop,
the official desktop application for the Telegram messaging service.

For license and copyright information please follow this link:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#pragma once

namespace Core::PreconfiguredProxyConfig {{

inline constexpr auto kHostBase64 = "{encode(host)}";
inline constexpr auto kSecretBase64 = "{encode(secret)}";
inline constexpr auto kPort = {port};

}} // namespace Core::PreconfiguredProxyConfig
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(contents, encoding="utf-8", newline="\n")
    print("Private MTProto header generated successfully (values not printed).")


if __name__ == "__main__":
    main()
