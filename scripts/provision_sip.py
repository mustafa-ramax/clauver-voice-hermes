#!/usr/bin/env python3
"""
Clauver SIP Provisioning Script.

Automates the Twilio + LiveKit SIP trunk setup so you don't have to
click through two dashboards. You provide credentials and a phone number,
this script does the rest.

Usage:
    cd ~/.clauver && .venv/bin/python scripts/provision_sip.py
"""

from __future__ import annotations

import asyncio
import getpass
import os
import random
import re
import string
import sys
from pathlib import Path

# --- Ensure we can import from project root ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = PROJECT_ROOT / ".env"


def _random_string(length: int, chars: str = string.ascii_lowercase + string.digits) -> str:
    return "".join(random.choices(chars, k=length))


def _print_header():
    print()
    print("╔═══════════════════════════════════════════════════╗")
    print("║  Clauver SIP Provisioning                        ║")
    print("║  Connects your Twilio number to LiveKit          ║")
    print("╚═══════════════════════════════════════════════════╝")
    print()
    print("  Before we start, you need:")
    print("    1. A Twilio account (twilio.com) with Account SID + Auth Token")
    print("    2. A LiveKit Cloud account (cloud.livekit.io) with URL + Key + Secret")
    print("    3. A phone number already purchased on Twilio")
    print()


def _input(prompt: str, secret: bool = False, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    full_prompt = f"  {prompt}{suffix}: "
    if secret:
        value = getpass.getpass(full_prompt)
    else:
        value = input(full_prompt)
    return value.strip() or default


def _check_twilio_installed():
    try:
        import twilio  # noqa: F401
        return True
    except ImportError:
        return False


def _install_twilio():
    print("  ⚠️  'twilio' package not found.")
    answer = _input("Install it now? [Y/n]") or "y"
    if answer.lower() != "y":
        print("  ❌ Cannot proceed without twilio. Install manually:")
        print(f"     {sys.executable} -m pip install twilio")
        sys.exit(1)
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "twilio"])
    print("  ✓ twilio installed")
    print()


def _validate_twilio(account_sid: str, auth_token: str):
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    try:
        client = Client(account_sid, auth_token)
        account = client.api.accounts(account_sid).fetch()
        print(f"  ✓ Connected to Twilio (Account: {account.friendly_name})")
        return client
    except TwilioRestException as e:
        print(f"  ❌ Twilio auth failed: {e.msg}")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Cannot connect to Twilio: {e}")
        sys.exit(1)


def _validate_livekit(url: str, api_key: str, api_secret: str):
    # Set env vars so LiveKitAPI picks them up
    os.environ["LIVEKIT_URL"] = url
    os.environ["LIVEKIT_API_KEY"] = api_key
    os.environ["LIVEKIT_API_SECRET"] = api_secret
    print("  ✓ LiveKit credentials saved")


def _list_twilio_numbers(client) -> list:
    numbers = client.incoming_phone_numbers.list(limit=50)
    if not numbers:
        print("  ❌ No phone numbers found on your Twilio account.")
        print("     Buy one at: twilio.com/console/phone-numbers/search")
        sys.exit(1)
    return numbers


def _find_existing_clauver_trunk(client) -> str | None:
    """Check if a clauver trunk already exists on Twilio."""
    trunks = client.trunking.v1.trunks.list(limit=50)
    for t in trunks:
        if t.friendly_name and "clauver" in t.friendly_name.lower():
            return t.sid
        if t.domain_name and "clauver" in t.domain_name.lower():
            return t.sid
    return None


def _create_twilio_trunk(client, phone_number_sid: str, phone_number: str):
    """Create Twilio SIP trunk with termination, credentials, and number assignment."""
    from twilio.base.exceptions import TwilioRestException

    # Generate unique domain and credentials
    domain_suffix = _random_string(6)
    domain_name = f"clauver-{domain_suffix}.pstn.twilio.com"
    sip_username = f"clauver_{_random_string(8)}"
    sip_password = _random_string(24, string.ascii_letters + string.digits)

    print(f"  Creating Twilio SIP trunk ({domain_name})...", end=" ", flush=True)

    # Create trunk (retry with different domain if taken)
    trunk = None
    for attempt in range(3):
        try:
            trunk = client.trunking.v1.trunks.create(
                friendly_name="Clauver Voice",
                domain_name=domain_name,
            )
            break
        except TwilioRestException as e:
            if "unique" in str(e).lower() or "already" in str(e).lower():
                domain_suffix = _random_string(6)
                domain_name = f"clauver-{domain_suffix}.pstn.twilio.com"
            else:
                raise

    if not trunk:
        print("✗")
        print("  ❌ Could not create trunk after 3 attempts.")
        sys.exit(1)
    print("✓")

    # Create credential list
    print("  Setting termination credentials...", end=" ", flush=True)
    cred_list = client.sip.credential_lists.create(friendly_name="Clauver SIP Auth")
    client.sip.credential_lists(cred_list.sid).credentials.create(
        username=sip_username, password=sip_password
    )
    # Associate with trunk
    client.trunking.v1.trunks(trunk.sid).credential_lists.create(
        credential_list_sid=cred_list.sid
    )
    print("✓")

    # Assign phone number
    print("  Assigning phone number to trunk...", end=" ", flush=True)
    client.trunking.v1.trunks(trunk.sid).phone_numbers.create(
        phone_number_sid=phone_number_sid
    )
    print("✓")

    return {
        "trunk_sid": trunk.sid,
        "domain_name": domain_name,
        "sip_username": sip_username,
        "sip_password": sip_password,
        "phone_number": phone_number,
    }


async def _create_livekit_trunk(domain_name: str, sip_username: str, sip_password: str, phone_number: str) -> str:
    """Create LiveKit outbound SIP trunk. Returns trunk ID."""
    from livekit import api
    from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo

    print("  Creating LiveKit outbound trunk...", end=" ", flush=True)

    lkapi = api.LiveKitAPI()
    try:
        trunk_info = SIPOutboundTrunkInfo(
            name="Clauver Outbound",
            address=domain_name,
            numbers=[phone_number],
            auth_username=sip_username,
            auth_password=sip_password,
        )
        result = await lkapi.sip.create_sip_outbound_trunk(
            CreateSIPOutboundTrunkRequest(trunk=trunk_info)
        )
        trunk_id = result.sip_trunk_id
        print("✓")
        return trunk_id
    except Exception as e:
        print("✗")
        print(f"  ❌ LiveKit error: {e}")
        sys.exit(1)
    finally:
        await lkapi.aclose()


def _update_env(values: dict[str, str]):
    """Update .env file, preserving existing content."""
    # Backup
    if ENV_FILE.exists():
        backup = ENV_FILE.with_suffix(".env.backup")
        backup.write_text(ENV_FILE.read_text())

    # Read existing
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []

    for key, value in values.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$")
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n")


def _confirm(summary: dict):
    print()
    print("  ─── Summary ───")
    print(f"    Twilio trunk:    {summary['domain_name']}")
    print(f"    Phone number:    {summary['phone_number']}")
    print(f"    LiveKit trunk:   {summary['livekit_trunk_id']}")
    print()
    answer = _input("Write to .env and finish? [Y/n]") or "y"
    return answer.lower() == "y"


async def main():
    _print_header()

    # --- Check twilio package ---
    if not _check_twilio_installed():
        _install_twilio()

    # --- Step 1: Twilio credentials ---
    print("─── Step 1: Twilio Credentials ───")
    print()
    twilio_sid = _input("Twilio Account SID")
    twilio_token = _input("Twilio Auth Token", secret=True)
    print()
    client = _validate_twilio(twilio_sid, twilio_token)
    print()

    # --- Step 2: LiveKit credentials ---
    print("─── Step 2: LiveKit Credentials ───")
    print()
    lk_url = _input("LiveKit URL (wss://...)")
    lk_key = _input("LiveKit API Key")
    lk_secret = _input("LiveKit API Secret", secret=True)
    print()
    _validate_livekit(lk_url, lk_key, lk_secret)
    print()

    # --- Step 3: Phone number ---
    print("─── Step 3: Phone Number ───")
    print()
    numbers = _list_twilio_numbers(client)
    print("  Your Twilio numbers:")
    for i, n in enumerate(numbers, 1):
        label = n.friendly_name or n.phone_number
        print(f"    {i}. {n.phone_number} ({label})")
    print()

    if len(numbers) == 1:
        choice = 1
        print(f"  Using: {numbers[0].phone_number}")
    else:
        raw = _input(f"Select number [1-{len(numbers)}]")
        try:
            choice = int(raw)
            if choice < 1 or choice > len(numbers):
                raise ValueError
        except ValueError:
            print("  ❌ Invalid selection.")
            sys.exit(1)
        print(f"  Using: {numbers[choice - 1].phone_number}")
    print()

    selected = numbers[choice - 1]

    # --- Check for existing trunk ---
    existing_sid = _find_existing_clauver_trunk(client)
    if existing_sid:
        print(f"  ⚠️  Found existing Clauver trunk on Twilio (SID: {existing_sid})")
        answer = _input("Create a new one anyway? [y/N]") or "n"
        if answer.lower() != "y":
            print("  Keeping existing trunk. Run again if you want to recreate.")
            sys.exit(0)
        print()

    # --- Step 4: Provision ---
    print("─── Step 4: Provisioning ───")
    print()

    twilio_result = _create_twilio_trunk(client, selected.sid, selected.phone_number)
    livekit_trunk_id = await _create_livekit_trunk(
        twilio_result["domain_name"],
        twilio_result["sip_username"],
        twilio_result["sip_password"],
        twilio_result["phone_number"],
    )
    print()

    # --- Step 5: Confirm and save ---
    summary = {
        **twilio_result,
        "livekit_trunk_id": livekit_trunk_id,
        "livekit_url": lk_url,
        "livekit_key": lk_key,
        "livekit_secret": lk_secret,
    }

    if not _confirm(summary):
        print("  Aborted. Trunks were created but .env was not updated.")
        print(f"  Your SIP_OUTBOUND_TRUNK_ID is: {livekit_trunk_id}")
        return

    print()
    print("─── Step 5: Saving to .env ───")
    print()
    _update_env({
        "LIVEKIT_URL": lk_url,
        "LIVEKIT_API_KEY": lk_key,
        "LIVEKIT_API_SECRET": lk_secret,
        "SIP_OUTBOUND_TRUNK_ID": livekit_trunk_id,
    })
    print("  ✓ .env updated")
    print()

    print("═══════════════════════════════════════════════════════")
    print("✅ Done! Your Clauver is ready to make calls.")
    print()
    print(f"  Test: Tell Hermes \"Call {selected.phone_number} and say hello\"")
    print("═══════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    asyncio.run(main())
